"""The simulated ESP32 runtime.

Connects to MQTT, subscribes to its station command topic, and executes
physical deposit plans. Every physical observation is published as sensor
telemetry / state events; the terminal deposit_result is what the BACKEND
validates (position match, weight, stability, beam, mechanical confirmation).
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from camera import CaptureUploader
from config import sim_config
from hardware import (
    BeamSensor,
    Carriage,
    JamError,
    LoadCell,
    MachineState,
    PositionSensor,
    Station,
    settle_profile,
)
from mqtt_client import SimulatorMqttClient
from scenarios import DepositPlan, SCENARIOS, get_scenario

logger = logging.getLogger("sim.engine")

# Knob for tests/CI: 0 disables the in-protocol sleep so plans run instantly.
_RAMP_STEP = float(os.environ.get("SIMULATOR_RAMP_STEP", "0.05"))


def _sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


class EcoLoopSimulator:
    """One station instance acting as the future ESP32."""

    def __init__(
        self,
        config=None,
        mqtt: SimulatorMqttClient | None = None,
        carriage: Carriage | None = None,
        load_cell: LoadCell | None = None,
        station: Station | None = None,
        capture_uploader: "CaptureUploader | None" = None,
    ) -> None:
        self.cfg = config or sim_config
        self.mqtt = mqtt or SimulatorMqttClient(
            self.cfg.broker_host,
            self.cfg.broker_port,
            client_id=f"sim-{self.cfg.station_code.lower()}",
            username=self.cfg.mqtt_username,
            password=self.cfg.mqtt_password,
            tls=self.cfg.mqtt_tls,
        )
        carriage = carriage or Carriage(initial_position=1, movement_time_per_step=self.cfg.movement_time_seconds)
        load_cell = load_cell or LoadCell(noise_grams=self.cfg.sensor_noise_grams)
        beam = BeamSensor()
        self.station = station or Station(
            carriage=carriage,
            load_cell=load_cell,
            beam=beam,
            position_sensor=PositionSensor(self.cfg.positions, carriage.current_position),
        )
        # The simulated station camera: picks a real frame and uploads it to
        # the backend `POST /api/v1/deposit/capture` endpoint when asked.
        self.capture = capture_uploader or CaptureUploader(self.cfg)
        self._running = False

    # -- lifecycle ----------------------------------------------------------------

    def start(self, hold: bool = True) -> None:
        """Connects, subscribes, starts heartbeat. Blocks until Ctrl+C when
        `hold` is True so the CLI appears as a long-running ESP32 substitute."""
        self.mqtt.set_command_handler(self._on_command)
        self.mqtt.start(self.cfg.command_topic())
        logger.info("Station: %s", self.cfg.station_code)
        logger.info("Status: ONLINE")
        logger.info("Heartbeat: starting")
        logger.info("[MQTT] waiting for commands on %s", self.cfg.command_topic())
        self._running = True
        while self._running and hold:
            self._heartbeat()
            _sleep(self.cfg.heartbeat_seconds)

    def stop(self) -> None:
        self._running = False
        self.mqtt.stop()

    # -- MQTT handler ---------------------------------------------------------------

    def _on_command(self, command: dict) -> None:
        kind = command.get("command")
        if kind not in ("route", "capture_request"):
            logger.info("[CMD] ignoring %r", command.get("command"))
            return
        operation_id = command.get("operation_id")
        if kind == "capture_request":
            logger.info("[CMD] capture_request operation=%s", operation_id)
            try:
                self.capture.upload(operation_id)
            except Exception:
                logger.exception("[SIM] capture upload failed for %s", operation_id)
            return
        destination = int(command.get("destination_position") or 0)
        logger.info("[CMD] route operation=%s destination=%s", operation_id, destination)
        try:
            self.run_plan(operation_id, destination, DepositPlan())
        except Exception:
            logger.exception("[SIM] plan execution failed for %s", operation_id)

    def run_plan(self, operation_id: str, destination: int | None, plan: DepositPlan) -> dict:
        """Executes a physical deposit plan for one operation and returns the
        terminal deposit_result exactly as published."""
        machine = self.station.machine
        effective_destination = plan.destination_position if plan.destination_position is not None else destination
        logger.info("[SIM] plan=%s op=%s destination=%s", plan.name, operation_id, effective_destination)

        machine.transition(MachineState.ROUTING)
        self._emit(operation_id, "state_changed", state="ROUTING", destination_position=effective_destination)
        self.station.carriage.jam_at_step = plan.jam_at_step

        machine.transition(MachineState.MOVING)
        self._emit(operation_id, "state_changed", state="MOVING")

        target = effective_destination if plan.actual_position is None else plan.actual_position
        try:
            for pos in self.station.carriage.move_to(target):
                self.station.position_sensor.set(pos)
                self._sensor(operation_id, carriage_position=pos, current_position=pos)
        except JamError as exc:
            return self._jammed(operation_id, plan, str(exc))

        machine.transition(MachineState.POSITIONED)
        self._emit(operation_id, "state_changed", state="POSITIONED", carriage_position=target)

        if plan.actual_position is not None and plan.actual_position != effective_destination:
            # The carriage physically settled at a position that disagrees with
            # the routing instruction -> wrong-position deposit.
            machine.transition(MachineState.WRONG_POSITION)
            self._emit(operation_id, "state_changed", state="WRONG_POSITION", actual_position=target)
            self._sensor(operation_id, carriage_position=target, current_position=target,
                         weight_grams=plan.final_weight or 18.4)
            terminal = self._terminal(operation_id, plan, actual_position=target,
                                      weight=plan.final_weight or 18.4,
                                      status=plan.emit_machine_status, mechanical=plan.mechanical_confirmed)
            self._reset(operation_id)
            return terminal

        machine.transition(MachineState.READY_FOR_DEPOSIT)
        self._emit(operation_id, "state_changed", state="READY_FOR_DEPOSIT")

        machine.transition(MachineState.DETECTING)
        if plan.beam_seen:
            self.station.beam.set(True)
        self._sensor(operation_id, beam_broken=self.station.beam.broken, weight_grams=0.0)
        self._emit(operation_id, "state_changed", state="DETECTING")

        machine.transition(MachineState.MEASURING)
        self._emit(operation_id, "state_changed", state="MEASURING")
        final_weight = self._run_weight_ramp(operation_id, plan)
        self.station.beam.set(False)
        self._sensor(operation_id, beam_broken=False, weight_stable=True, weight_grams=final_weight)

        if plan.emit_machine_status != "confirmed":
            machine.transition(MachineState.UNDERWEIGHT if plan.emit_machine_status == "underweight" else MachineState.SENSOR_ERROR)
            self._emit(operation_id, "state_changed", state=machine.state.value, weight_grams=final_weight)
            terminal = self._terminal(operation_id, plan, actual_position=self.station.position_sensor.read(),
                                      weight=final_weight, status=plan.emit_machine_status,
                                      mechanical=False)
            self._reset(operation_id)
            return terminal

        machine.transition(MachineState.DEPOSIT_CONFIRMED)
        self._emit(operation_id, "state_changed", state="DEPOSIT_CONFIRMED")

        if plan.delay_before_terminal > 0 and _RAMP_STEP > 0:
            _sleep(plan.delay_before_terminal)

        terminal = self._terminal(operation_id, plan, actual_position=self.station.position_sensor.read(),
                                  weight=final_weight, status=plan.emit_machine_status,
                                  mechanical=plan.mechanical_confirmed)
        self._reset(operation_id)

        if plan.duplicate_terminal:
            self._publish_terminal(operation_id, terminal)
        return terminal

    # -- helpers ---------------------------------------------------------------------

    def _jammed(self, operation_id: str, plan: DepositPlan, reason: str) -> dict:
        machine = self.station.machine
        machine.transition(MachineState.JAMMED)
        self._emit(operation_id, "state_changed", state="JAMMED", reason=reason)
        terminal = self._terminal(operation_id, plan, actual_position=self.station.carriage.current_position,
                                  weight=0.0, status="jam", mechanical=False, beam_seen=False)
        self._reset(operation_id)
        return terminal

    def _reset(self, operation_id: str) -> None:
        machine = self.station.machine
        if machine.can_transition(MachineState.RESETTING):
            machine.transition(MachineState.RESETTING)
            self._emit(operation_id, "state_changed", state="RESETTING")
        if machine.can_transition(MachineState.IDLE):
            machine.transition(MachineState.IDLE)
            self._emit(operation_id, "state_changed", state="IDLE")

    def _run_weight_ramp(self, operation_id: str, plan: DepositPlan) -> float:
        ramp = settle_profile(plan.weight_timeline)
        last_t = plan.weight_timeline[-1][0]
        final_value = plan.final_weight if plan.final_weight is not None else ramp(last_t)

        if _RAMP_STEP <= 0:
            # Fast path (tests/CI): one reading at the settled weight.
            self.station.load_cell.set_value(final_value)
            reading = self.station.load_cell.read_weight()
            self._sensor(
                operation_id,
                weight_grams=reading,
                weight_stable=True,
                beam_broken=True,
                carriage_position=self.station.position_sensor.read(),
            )
            return round(reading, 2)

        t = 0.0
        while t <= last_t + 1e-9:
            self.station.load_cell.set_value(ramp(t))
            reading = self.station.load_cell.read_weight()
            self._sensor(
                operation_id,
                weight_grams=reading,
                weight_stable=(t >= last_t),
                beam_broken=True,
                carriage_position=self.station.position_sensor.read(),
            )
            _sleep(_RAMP_STEP)
            t += _RAMP_STEP
        self.station.load_cell.set_value(final_value)
        return round(self.station.load_cell.read_weight(), 2)

    def _terminal(
        self,
        operation_id: str,
        plan: DepositPlan,
        actual_position: int,
        weight: float,
        status: str,
        mechanical: bool,
        beam_seen: bool = True,
    ) -> dict:
        terminal = {
            "station_id": self.cfg.station_code,
            "operation_id": operation_id,
            "event": "deposit_result",
            "status": status,
            "actual_position": actual_position,
            "carriage_position": self.station.position_sensor.read(),
            "weight_grams": round(weight, 2),
            "weight_stable": weight >= self.cfg.min_weight_grams,
            "beam_event_seen": beam_seen,
            "mechanical_confirmed": mechanical,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._publish_terminal(operation_id, terminal)
        return terminal

    def _publish_terminal(self, operation_id: str, terminal: dict) -> None:
        self.mqtt.publish(self.cfg.topic("event"), terminal)
        logger.info("[TERMINAL] operation=%s status=%s", operation_id, terminal["status"])

    def _emit(self, operation_id: str, event: str, state: str, **extra) -> None:
        payload = {
            "station_id": self.cfg.station_code,
            "operation_id": operation_id,
            "event": event,
            "state": state,
            **extra,
        }
        self.mqtt.publish(self.cfg.topic("event"), payload)

    def _sensor(self, operation_id: str, **fields) -> None:
        payload = {
            "station_id": self.cfg.station_code,
            "operation_id": operation_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        self.mqtt.publish(self.cfg.topic("sensor"), payload)

    def _heartbeat(self) -> None:
        payload = {
            "station_id": self.cfg.station_code,
            "status": "online",
            "state": self.station.state.value,
            "carriage_position": self.station.carriage.current_position,
            "uptime_s": 0,
        }
        self.mqtt.publish(self.cfg.topic("heartbeat"), payload)
        logger.info("Heartbeat: OK")


def make_cli_simulator(config=None):
    """Builds a fully-wired simulator for the `simulator.py` CLI entrypoint."""
    return EcoLoopSimulator(config=config or sim_config)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="EcoLoop hardware simulator — behaves like the future ESP32 "
        "firmware on the documented MQTT contract."
    )
    parser.add_argument("--broker", default=None, help="MQTT broker host (default: env MQTT_BROKER_HOST)")
    parser.add_argument("--port", type=int, default=None, help="MQTT broker port (default: env MQTT_BROKER_PORT)")
    parser.add_argument(
        "--scenario",
        default=None,
        help="Run a single scenario once after subscribing, then exit. "
        "One of: " + ", ".join(sorted(SCENARIOS)),
    )
    parser.add_argument(
        "--loop-scenario",
        default=None,
        help="Run the given scenario on a fixed operation id in a loop until Ctrl+C.",
    )
    args = parser.parse_args()

    from config import SimConfig

    cfg = SimConfig()
    if args.broker:
        cfg.broker_host = args.broker
    if args.port:
        cfg.broker_port = args.port

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    sim = make_cli_simulator(cfg)

    if args.scenario:
        plan = get_scenario(args.scenario)
        sim.mqtt.set_command_handler(lambda cmd: None)
        sim.mqtt.start(cfg.command_topic())
        # Drop-in: use a fixed operation id so a tester/backend can observe it.
        sim.run_plan("OP-DEMO-000001", plan.destination_position or 1, plan)
        sim.stop()
        return

    sim.start(hold=True)


if __name__ == "__main__":
    main()