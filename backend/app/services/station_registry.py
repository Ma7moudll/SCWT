"""In-memory live state for stations, fed by MQTT heartbeat/state telemetry.

The DB holds the authoritative station list; this registry holds the volatile
sensor snapshot (positions, weight, door states) the UI renders in real time.
"""
from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

POSITIONS = {1: "plastic", 2: "metal", 3: "paper", 4: "other"}


@dataclass
class StationSnapshot:
    station_id: str
    code: str
    name: str
    status: str = "offline"
    state: str = "IDLE"
    carriage_position: int = 0
    current_position: int = 0
    door_state: str = "CLOSED"
    weight_grams: float = 0.0
    weight_stable: bool = False
    beam_broken: bool = False
    operation_id: str | None = None
    last_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compartment_readiness(self) -> dict[str, str]:
        ready = self.carriage_position if self.carriage_position in POSITIONS else None
        return {
            POSITIONS[pos]: "READY" if pos == ready else "CLOSED"
            for pos in sorted(POSITIONS)
        }

    def to_dict(self) -> dict:
        return asdict(self)


class StationRegistry:
    def __init__(self) -> None:
        self._snapshots: dict[str, StationSnapshot] = {}
        self._lock = threading.Lock()

    def register(self, snapshot: StationSnapshot) -> None:
        with self._lock:
            self._snapshots[snapshot.station_id] = snapshot

    def get(self, station_id: str) -> StationSnapshot | None:
        with self._lock:
            return self._snapshots.get(station_id)

    def list(self) -> list[StationSnapshot]:
        with self._lock:
            return list(self._snapshots.values())

    def update(self, station_id: str, **fields) -> StationSnapshot | None:
        with self._lock:
            snap = self._snapshots.get(station_id)
            if snap is None:
                return None
            for key, value in fields.items():
                if hasattr(snap, key):
                    setattr(snap, key, value)
            snap.last_seen = datetime.now(timezone.utc).isoformat()
            return snap


registry = StationRegistry()