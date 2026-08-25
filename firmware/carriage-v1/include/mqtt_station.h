// =============================================================================
// MQTT station layer — implements docs/mqtt-contract.md verbatim (§19/§20).
//
//  subscribe: ecoloop/stations/{code}/command
//  publish:   .../event    state_changed + terminal deposit_result
//             .../sensor   telemetry (mechanism_position, weight, beam)
//             .../heartbeat  liveness incl. mechanism = "rotary"
//
// Safety: if the broker connection drops while the mechanism is moving, the
// controller is driven to its safe state immediately (§20). Commands carry an
// operation_id; a repeated route for the same operation is ignored (§21).
// =============================================================================
#pragma once
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <WiFiClient.h>

#include <functional>

#include "station_fsm.h"

class MqttStationLayer {
 public:
  MqttStationLayer(const char* code, const char* prefix);

  void begin(const char* user, const char* pass, const char* host, uint16_t port);
  void loop();
  bool connected();

  // Outgoing contract messages.
  void publishState(const char* operationId, const char* state,
                    std::function<void(JsonObject&)> extra = {});
  void publishSensor(std::function<void(JsonObject&)> fill = {});
  void publishTerminal(const char* operationId, const char* status,
                       uint8_t actualPosition, uint8_t mechanismPosition,
                       float weightGrams, bool weightStable, bool beamSeen,
                       bool mechanicalConfirmed);
  void publishHeartbeat(const char* state, uint8_t mechanismPosition);

  // Incoming command hook: returns true when a NEW route was accepted.
  std::function<bool(const char* operationId, uint8_t destinationPosition)> onRoute;
  std::function<void(const char* operationId)> onCaptureRequest;

 private:
  void reconnect();
  static void _staticOnMessage(char* topic, byte* payload, unsigned int len);
  String commandTopic() const;

  const char* code_;
  const char* prefix_;
  WiFiClient wifi_;
  PubSubClient mqtt_{wifi_};
  char lastRouteOperation_[40] = {0};  // §21 idempotency guard
};
