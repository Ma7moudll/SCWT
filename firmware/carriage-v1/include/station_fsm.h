// =============================================================================
// Station FSM — the deposit lifecycle (§18). Mirrors the Recycle Vision
// MachineState contract exactly (both mechanisms share one lifecycle):
//
// IDLE -> ROUTING -> MOVING -> POSITIONED -> READY_FOR_DEPOSIT -> DETECTING
//      -> MEASURING -> DEPOSIT_CONFIRMED -> RESETTING -> IDLE
// Errors: JAMMED / WRONG_POSITION / UNDERWEIGHT / SENSOR_ERROR / TIMEOUT -> RESETTING
// =============================================================================
#pragma once
#include <Arduino.h>

enum class StationState : uint8_t {
  IDLE = 0,
  ROUTING,
  MOVING,
  POSITIONED,
  READY_FOR_DEPOSIT,
  DETECTING,
  MEASURING,
  DEPOSIT_CONFIRMED,
  RESETTING,
  JAMMED,
  WRONG_POSITION,
  UNDERWEIGHT,
  SENSOR_ERROR,
  TIMEOUT,
};

const char* stationStateName(StationState s);

class StationFsm {
 public:
  explicit StationFsm(StationState initial = StationState::IDLE) : state_(initial) {}

  bool can(StationState next) const;
  bool transition(StationState next);
  StationState state() const { return state_; }
  const char* name() const { return stationStateName(state_); }
  bool isError() const;

 private:
  StationState state_;
};
