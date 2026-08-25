#include "station_fsm.h"

static const char* kNames[] = {
    "IDLE",    "ROUTING",   "MOVING",       "POSITIONED",
    "READY_FOR_DEPOSIT",    "DETECTING",    "MEASURING",
    "DEPOSIT_CONFIRMED",    "RESETTING",    "JAMMED",
    "WRONG_POSITION",       "UNDERWEIGHT",  "SENSOR_ERROR", "TIMEOUT"};

const char* stationStateName(StationState s) {
  return kNames[static_cast<uint8_t>(s)];
}

static bool allowed(StationState from, StationState to) {
  switch (from) {
    case StationState::IDLE:
      return to == StationState::ROUTING;
    case StationState::ROUTING:
      return to == StationState::MOVING;
    case StationState::MOVING:
      return to == StationState::POSITIONED || to == StationState::JAMMED ||
             to == StationState::WRONG_POSITION || to == StationState::TIMEOUT ||
             to == StationState::SENSOR_ERROR;
    case StationState::POSITIONED:
      return to == StationState::READY_FOR_DEPOSIT ||
             to == StationState::JAMMED || to == StationState::WRONG_POSITION;
    case StationState::READY_FOR_DEPOSIT:
      return to == StationState::DETECTING;
    case StationState::DETECTING:
      return to == StationState::MEASURING ||
             to == StationState::SENSOR_ERROR;
    case StationState::MEASURING:
      return to == StationState::DEPOSIT_CONFIRMED ||
             to == StationState::UNDERWEIGHT ||
             to == StationState::SENSOR_ERROR;
    case StationState::DEPOSIT_CONFIRMED:
      return to == StationState::RESETTING;
    case StationState::RESETTING:
      return to == StationState::IDLE;
    default:  // every error state recovers through RESETTING
      return to == StationState::RESETTING;
  }
}

bool StationFsm::can(StationState next) const { return allowed(state_, next); }

bool StationFsm::transition(StationState next) {
  if (!allowed(state_, next)) return false;
  state_ = next;
  return true;
}

bool StationFsm::isError() const {
  switch (state_) {
    case StationState::JAMMED:
    case StationState::WRONG_POSITION:
    case StationState::UNDERWEIGHT:
    case StationState::SENSOR_ERROR:
    case StationState::TIMEOUT:
      return true;
    default:
      return false;
  }
}
