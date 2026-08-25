#include "carriage_controller.h"

static CarriageController* g_tick_instance = nullptr;

CarriageController::CarriageController(uint8_t pinStep, uint8_t pinDir,
                                       uint8_t pinEnable, uint8_t pinHomeSwitch,
                                       const CarriageConfig& cfg)
    : stepper_(AccelStepper::DRIVER, pinStep, pinDir),
      pinEnable_(pinEnable),
      pinHomeSwitch_(pinHomeSwitch),
      cfg_(cfg) {}

void CarriageController::begin() {
  pinMode(pinEnable_, OUTPUT);
  pinMode(pinHomeSwitch_, INPUT_PULLUP);
  digitalWrite(pinEnable_, HIGH);  // driver disabled at rest
  stepper_.setMaxSpeed(cfg_.maxMmPerSec);
  stepper_.setAcceleration(cfg_.accelMmPerS2);
}

float CarriageController::positionToMm(uint8_t position) const {
  return (position - 1) * cfg_.positionPitchMm;  // position 1 == home == 0 mm
}

bool CarriageController::startHoming() {
  if (status_ == CarriageStatus::ESTOP || isMoving()) return false;
  status_ = CarriageStatus::HOMING;
  stepper_.setMaxSpeed(40.0f);
  stepper_.move(-0x7FFFFFFF);  // seek toward the home limit switch
  motionStartMs_ = millis();
  return true;
}

bool CarriageController::routeToPosition(uint8_t position) {
  if (!homed_ || isMoving() || status_ == CarriageStatus::ESTOP) return false;
  if (position < 1 || position > 4) return false;
  float mm = positionToMm(position);
  if (fabsf(mm - currentMm_) < 0.5f) return true;  // already there (§21)
  targetMm_ = mm;
  stepper_.setMaxSpeed(cfg_.maxMmPerSec);
  stepper_.move(static_cast<long>(mm * (cfg_.stepsPerRev * cfg_.microstepping / cfg_.mmPerRev)));
  motionStartMs_ = millis();
  lastProgressMs_ = motionStartMs_;
  status_ = CarriageStatus::MOVING;
  return true;
}

void CarriageController::tick() {
  if (g_tick_instance == nullptr) g_tick_instance = this;
  if (status_ == CarriageStatus::HOMING) {
    stepper_.run();
    digitalWrite(pinEnable_, LOW);
    uint32_t now = millis();
    if (digitalRead(pinHomeSwitch_) == LOW) {          // hit the limit
      stepper_.setCurrentPosition(0);
      currentMm_ = 0.0f;
      stepper_.setMaxSpeed(cfg_.maxMmPerSec);
      stepper_.move(static_cast<long>(3.0f * (cfg_.stepsPerRev * cfg_.microstepping / cfg_.mmPerRev)));
      status_ = CarriageStatus::MOVING;                 // back-off move
      homed_ = true;                                    // referenced
    } else if (now - motionStartMs_ > 10000.0f) {
      emergencyStop();                                  // §25: never seek forever
    }
    return;
  }
  if (status_ != CarriageStatus::MOVING) return;
  stepper_.run();
  digitalWrite(pinEnable_, LOW);
  int32_t pos = stepper_.currentPosition();
  if (pos != lastProgressMs_) lastProgressMs_ = millis();
  uint32_t now = millis();
  if (now - motionStartMs_ > 6000.0f) {
    stepper_.stop();
    emergencyStop();
    status_ = CarriageStatus::JAMMED;                   // §25 stall watchdog
    return;
  }
  if (stepper_.distanceToGo() == 0) {
    currentMm_ = targetMm_;
    status_ = CarriageStatus::IDLE;
    digitalWrite(pinEnable_, HIGH);                     // de-energize at rest
  }
}

void CarriageController::emergencyStop() {
  stepper_.stop();
  digitalWrite(pinEnable_, HIGH);
  if (!homed_) status_ = CarriageStatus::ESTOP;
}

void CarriageController::clearEstop() {
  status_ = homed_ ? CarriageStatus::IDLE : CarriageStatus::UNHOMED;
}

uint8_t CarriageController::carriagePosition() const {
  for (uint8_t p = 1; p <= 4; ++p) {
    if (fabsf(currentMm_ - positionToMm(p)) < 2.0f) return p;
  }
  return 0;
}

bool CarriageController::isMoving() const {
  return status_ == CarriageStatus::MOVING || status_ == CarriageStatus::HOMING;
}
