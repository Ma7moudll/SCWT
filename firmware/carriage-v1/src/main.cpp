// =============================================================================
// Ecolamp Station — CARRIAGE firmware entrypoint (independent product).
// Layers: MQTT layer -> Station FSM -> CarriageController -> driver.
// =============================================================================
#include <Arduino.h>
#include <HX711.h>
#include <VL53L1X.h>
#include <Wire.h>

#include "carriage_controller.h"
#include "config.h"
#include "mqtt_station.h"
#include "station_fsm.h"

static CarriageConfig cfg{STEPS_PER_REV, MICROSTEPPING, MM_PER_REV,
                          POSITION_PITCH_MM, MAX_MM_PER_SEC, ACCEL_MM_PER_S2};
static CarriageController carriage(PIN_STEP, PIN_DIR, PIN_ENABLE,
                                   PIN_HOME_SWITCH, cfg);
static MqttStationLayer mqttLayer(STATION_CODE, MQTT_TOPIC_PREFIX);
static StationFsm fsm;

static HX711 loadCell;
static VL53L1X tof[4];
static float preWeight = 0.0f;
static char activeOperation[40] = {0};
static uint8_t routedPosition = 0;
static uint32_t lastHeartbeat = 0;

void enterSafeState(const char* reason);
float readScale();
void publishResult(const char* status, uint8_t actual, float grams,
                   bool stable, bool beam);
void resetToIdle();
void driveOperation();

void setup() {
  Serial.begin(115200);
  carriage.begin();
  Wire.begin();
  loadCell.begin(PIN_HX_DOUT, PIN_HX_SCK);
  loadCell.set_scale(LC_CALIBRATION);
  loadCell.tare();
  for (uint8_t i = 0; i < 4; ++i) {
    pinMode(PIN_TOF_XSHUT[i], OUTPUT);
    digitalWrite(PIN_TOF_XSHUT[i], LOW);
  }
  for (uint8_t i = 0; i < 4; ++i) {
    digitalWrite(PIN_TOF_XSHUT[i], HIGH);
    delay(10);
    tof[i].setTimeout(50);
    if (!tof[i].init()) continue;
    tof[i].setDistanceMode(VL53L1X::Long);
    tof[i].setAddress(TOF_ADDR[i]);
    tof[i].startContinuous(100);
  }

  if (!carriage.startHoming()) enterSafeState("homing refused");
  while (carriage.isMoving()) carriage.tick();
  if (carriage.status() != CarriageStatus::IDLE) enterSafeState("homing failed");

  mqttLayer.begin(MQTT_USER, MQTT_PASS, MQTT_HOST, MQTT_PORT);
  mqttLayer.onRoute = [](const char* op, uint8_t dest) -> bool {
    if (fsm.state() != StationState::IDLE) return false;
    strncpy(activeOperation, op, sizeof(activeOperation) - 1);
    routedPosition = dest;
    fsm.transition(StationState::ROUTING);
    mqttLayer.publishState(op, "ROUTING",
                           [dest](JsonObject& o) { o["destination_position"] = dest; });
    fsm.transition(StationState::MOVING);
    mqttLayer.publishState(op, "MOVING");
    preWeight = readScale();  // weigh the item inside the carriage
    return carriage.routeToPosition(dest);
  };
}

void loop() {
  mqttLayer.loop();
  carriage.tick();

  // §20: connectivity loss mid-motion -> safe state.
  if (!mqttLayer.connected() && carriage.isMoving()) {
    carriage.emergencyStop();
    enterSafeState("mqtt lost while moving");
  }

  driveOperation();

  if (millis() - lastHeartbeat > HEARTBEAT_MS) {
    lastHeartbeat = millis();
    mqttLayer.publishHeartbeat(fsm.name(), carriage.carriagePosition());
  }
}

void driveOperation() {
  if (fsm.state() != StationState::MOVING || routedPosition == 0) return;
  if (carriage.isMoving()) return;

  if (carriage.status() == CarriageStatus::JAMMED) {
    fsm.transition(StationState::JAMMED);
    mqttLayer.publishState(activeOperation, "JAMMED");
    publishResult("jam", carriage.carriagePosition(), 0.0f, false, false);
    resetToIdle();
    return;
  }
  if (carriage.status() != CarriageStatus::IDLE) {
    fsm.transition(StationState::SENSOR_ERROR);
    publishResult("sensor_error", carriage.carriagePosition(), 0.0f, false, false);
    resetToIdle();
    return;
  }

  const uint8_t actual = carriage.carriagePosition();
  if (actual != routedPosition) {
    fsm.transition(StationState::WRONG_POSITION);
    mqttLayer.publishState(activeOperation, "WRONG_POSITION");
    publishResult("confirmed", actual, fabsf(readScale() - preWeight), true, true);
    resetToIdle();
    return;
  }

  fsm.transition(StationState::POSITIONED);
  mqttLayer.publishState(activeOperation, "POSITIONED");
  // The carriage carries the item over the bin: release + it lands on the
  // bin's fill-sensor field; the in-carriage cell already captured the weight.
  fsm.transition(StationState::READY_FOR_DEPOSIT);
  mqttLayer.publishState(activeOperation, "READY_FOR_DEPOSIT");
  fsm.transition(StationState::DETECTING);
  mqttLayer.publishState(activeOperation, "DETECTING");
  uint32_t t0 = millis();
  bool itemGone = false;
  while (millis() - t0 < 4000) {          // wait for the carriage to unload
    float now = readScale();
    if (fabsf(now - preWeight) > MIN_DEPOSIT_G * 2.0f) continue;  // still loaded
    itemGone = fabsf(now) < MIN_DEPOSIT_G || fabsf(now - preWeight) > MIN_DEPOSIT_G;
    if (itemGone) break;
    yield();
  }
  float deposited = fabsf(preWeight);     // the weighed item left the carriage
  bool stable = deposited >= MIN_DEPOSIT_G && itemGone;

  fsm.transition(StationState::MEASURING);
  mqttLayer.publishState(activeOperation, "MEASURING");

  if (!stable) {
    fsm.transition(StationState::UNDERWEIGHT);
    publishResult("underweight", actual, deposited, false, itemGone);
    resetToIdle();
    return;
  }
  fsm.transition(StationState::DEPOSIT_CONFIRMED);
  mqttLayer.publishState(activeOperation, "DEPOSIT_CONFIRMED");
  publishResult("confirmed", actual, deposited, true, itemGone);
  resetToIdle();
}

void publishResult(const char* status, uint8_t actual, float grams,
                   bool stable, bool beam) {
  mqttLayer.publishTerminal(activeOperation, status, actual,
                            carriage.carriagePosition(), grams, stable, beam,
                            strcmp(status, "confirmed") == 0);
}

void resetToIdle() {
  fsm.transition(StationState::RESETTING);
  mqttLayer.publishState(activeOperation, "RESETTING");
  fsm.transition(StationState::IDLE);
  mqttLayer.publishState(activeOperation, "IDLE");
  activeOperation[0] = 0;
  routedPosition = 0;
}

void enterSafeState(const char* reason) {
  carriage.emergencyStop();
  Serial.printf("[SAFE] %s — manual recovery required\n", reason);
  while (true) {
    mqttLayer.loop();
    delay(10);
  }
}

float readScale() {
  if (!loadCell.wait_ready_timeout(200)) return 0.0f;
  return loadCell.get_units(3);
}
