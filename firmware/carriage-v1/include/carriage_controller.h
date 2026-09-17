// =============================================================================
// CarriageController — SCWT's mechanism abstraction.
//
// MQTT layer -> Station FSM -> CarriageController (HERE) -> stepper driver.
// Positions are 1..4 along a linear rail with a limit switch at position 1.
// =============================================================================
#pragma once
#include <AccelStepper.h>

struct CarriageConfig {
  float stepsPerRev;
  int microstepping;
  float mmPerRev;
  float positionPitchMm;
  float maxMmPerSec;
  float accelMmPerS2;
};

enum class CarriageStatus : uint8_t { UNHOMED, HOMING, IDLE, MOVING, JAMMED, ESTOP };

class CarriageController {
 public:
  CarriageController(uint8_t pinStep, uint8_t pinDir, uint8_t pinEnable,
                     uint8_t pinHomeSwitch, const CarriageConfig& cfg);

  void begin();
  bool startHoming();
  bool routeToPosition(uint8_t position);   // compartment index 1..4
  void tick();
  void emergencyStop();
  void clearEstop();

  CarriageStatus status() const { return status_; }
  uint8_t carriagePosition() const;         // 1..4, or 0 between slots
  bool isHomed() const { return homed_; }
  bool isMoving() const;

 private:
  float positionToMm(uint8_t position) const;
  bool startMoveToMm(float mm);

  AccelStepper stepper_;
  uint8_t pinEnable_, pinHomeSwitch_;
  CarriageConfig cfg_;
  CarriageStatus status_ = CarriageStatus::UNHOMED;
  bool homed_ = false;
  float currentMm_ = 0.0f, targetMm_ = 0.0f;
  uint32_t motionStartMs_ = 0, lastProgressMs_ = 0;
};
