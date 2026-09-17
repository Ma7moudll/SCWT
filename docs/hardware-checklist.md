# SCWT Station — Hardware Checklist

Build checklist for one physical CARRIAGE station. The simulator
(`hardware-simulator/`) mirrors every element below 1:1 on the wire.

## Motion

- [ ] NEMA 17 stepper + GT2 belt drive on the linear rail
- [ ] Stepper driver (A4988/TMC2209) with current limit set
- [ ] Limit switch at rail origin (homing reference)
- [ ] Position verification along the rail (switches/encoder)
- [ ] Carriage with item bay and release gate (servo)

## Sensing

- [ ] HX711 load cell mounted IN the carriage (per-item weighing)
- [ ] IR beam across the station opening (insertion check)
- [ ] Station camera (AI capture) aimed at the intake

## Controller

- [ ] ESP32 DevKit flashed from `firmware/carriage-v1/`
- [ ] `config.h` calibration: steps-per-position, speeds, homing order
- [ ] Wi-Fi credentials + broker host/port via config

## Station identity & provisioning

- [ ] Station registered in the backend DB (`station_code` = ST-…)
- [ ] Broker identity `station-<CODE>` created in the passwd file
- [ ] ACL block added for the station (read own command, write own telemetry)
- [ ] `STATION_API_KEY` provisioned for the camera capture path

## Acceptance (per station)

- [ ] `pio run -d firmware/carriage-v1` compiles clean for esp32dev
- [ ] Homing completes and reports position 1
- [ ] Route to each of the four positions ends with `mechanism == target`
- [ ] 18.4 g reference weight passes the underweight gate
- [ ] Beam break + clear observed on `sensor`
- [ ] Terminal `deposit_result` confirmed by the backend (points awarded)
