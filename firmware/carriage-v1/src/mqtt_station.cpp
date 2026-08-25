#include "mqtt_station.h"

#include <ArduinoJson.h>

#include "config.h"

static MqttStationLayer* g_instance = nullptr;

String MqttStationLayer::commandTopic() const {
  return String(prefix_) + "/" + code_ + "/command";
}

MqttStationLayer::MqttStationLayer(const char* code, const char* prefix)
    : code_(code), prefix_(prefix) {
  g_instance = this;
}

void MqttStationLayer::begin(const char* user, const char* pass,
                             const char* host, uint16_t port) {
  String clientId = String("carriage-") + code_;
  mqtt_.setServer(host, port);
  mqtt_.setCallback(MqttStationLayer::_staticOnMessage);
  mqtt_.setKeepAlive(15);
  // LWT: broker marks the station offline if it vanishes mid-operation.
  String willTopic = String(prefix_) + "/" + code_ + "/heartbeat";
  String lwt = String("{\"station_id\":\"") + code_ +
               "\",\"status\":\"offline\",\"mechanism\":\"" + STATION_MECHANISM +
               "\"}";
  mqtt_.connect(clientId.c_str(), user, pass, willTopic.c_str(), 1, true,
                lwt.c_str());
}

void MqttStationLayer::reconnect() {
  while (!mqtt_.connected()) {
    begin(MQTT_USER, MQTT_PASS, MQTT_HOST, MQTT_PORT);
    if (!mqtt_.connected()) delay(2000);  // TODO: exponential backoff
  }
  mqtt_.subscribe(commandTopic().c_str(), 1);  // QoS 1 per contract
}

void MqttStationLayer::loop() {
  if (!mqtt_.connected()) reconnect();
  mqtt_.loop();
}

bool MqttStationLayer::connected() { return mqtt_.connected(); }

void MqttStationLayer::_staticOnMessage(char* topic, byte* payload,
                                        unsigned int len) {
  if (g_instance == nullptr) return;
  JsonDocument doc;
  if (deserializeJson(doc, payload, len)) return;
  const char* kind = doc["command"] | "";
  const char* op = doc["operation_id"] | "";

  if (strcmp(kind, "capture_request") == 0) {
    if (g_instance->onCaptureRequest) g_instance->onCaptureRequest(op);
    return;
  }
  if (strcmp(kind, "route") != 0) return;

  uint8_t dest = doc["destination_position"] | 0;
  if (dest < 1 || dest > 4) return;
  // §21: duplicate route for the same operation is ignored.
  if (strncmp(g_instance->lastRouteOperation_, op,
              sizeof(g_instance->lastRouteOperation_)) == 0)
    return;
  strncpy(g_instance->lastRouteOperation_, op,
          sizeof(g_instance->lastRouteOperation_) - 1);
  if (g_instance->onRoute) g_instance->onRoute(op, dest);
}

static void publishJson(PubSubClient& client, const String& topic,
                        const JsonDocument& doc, bool retained) {
  String out;
  serializeJson(doc, out);
  client.publish(topic.c_str(), reinterpret_cast<const uint8_t*>(out.c_str()),
                 out.length(), retained);
}

void MqttStationLayer::publishState(const char* operationId, const char* state,
                                    std::function<void(JsonObject&)> extra) {
  JsonDocument doc;
  doc["station_id"] = code_;
  doc["operation_id"] = operationId;
  doc["event"] = "state_changed";
  doc["state"] = state;
  if (extra) {
    JsonObject o = doc.to<JsonObject>();
    extra(o);
  }
  publishJson(mqtt_, String(prefix_) + "/" + code_ + "/event", doc, false);
}

void MqttStationLayer::publishSensor(std::function<void(JsonObject&)> fill) {
  JsonDocument doc;
  doc["station_id"] = code_;
  doc["timestamp"] = static_cast<long long>(millis());
  if (fill) {
    JsonObject o = doc.to<JsonObject>();
    fill(o);
  }
  publishJson(mqtt_, String(prefix_) + "/" + code_ + "/sensor", doc, false);
}

void MqttStationLayer::publishTerminal(
    const char* operationId, const char* status, uint8_t actualPosition,
    uint8_t mechanismPosition, float weightGrams, bool weightStable,
    bool beamSeen, bool mechanicalConfirmed) {
  JsonDocument doc;
  doc["station_id"] = code_;
  doc["operation_id"] = operationId;
  doc["event"] = "deposit_result";
  doc["status"] = status;
  doc["actual_position"] = actualPosition;
  doc["mechanism_position"] = mechanismPosition;  // NEVER carriage_position
  doc["weight_grams"] = weightGrams;
  doc["weight_stable"] = weightStable;
  doc["beam_event_seen"] = beamSeen;
  doc["mechanical_confirmed"] = mechanicalConfirmed;
  doc["timestamp"] = static_cast<long long>(millis());
  publishJson(mqtt_, String(prefix_) + "/" + code_ + "/event", doc, false);
}

void MqttStationLayer::publishHeartbeat(const char* state,
                                        uint8_t mechanismPosition) {
  JsonDocument doc;
  doc["station_id"] = code_;
  doc["status"] = "online";
  doc["mechanism"] = STATION_MECHANISM;
  doc["state"] = state;
  doc["mechanism_position"] = mechanismPosition;
  doc["uptime_s"] = millis() / 1000;
  publishJson(mqtt_, String(prefix_) + "/" + code_ + "/heartbeat", doc, true);
}
