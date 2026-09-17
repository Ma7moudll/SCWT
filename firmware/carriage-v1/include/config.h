// =============================================================================
// SCWT Station — CARRIAGE firmware configuration.
//
// SCWT is an independent product built around the CARRIAGE sorting
// mechanism: a carriage travels along a linear rail and releases waste into
// the bin under the routed compartment. Every hardware value lives here (no
// magic numbers elsewhere). Recalibrate by editing this file or via CAL mode.
// =============================================================================
#pragma once

// ---------------------------------------------------------------- identity --
static const char* STATION_CODE      = "ST-001";
static const char* STATION_MECHANISM = "carriage";

// ------------------------------------------------------------------- WiFi ---
static const char* WIFI_SSID         = "scwt-station";
static const char* WIFI_PASS         = "change-me";
static const char* MQTT_HOST         = "192.168.1.20";
static const uint16_t MQTT_PORT      = 1886;
static const char* MQTT_USER         = "station-";    // + STATION_CODE at runtime
static const char* MQTT_PASS         = "change-me";
static const char* MQTT_TOPIC_PREFIX = "scwt/stations";

// ------------------------------------------------------------- stepper ------
// GT2 belt drive, 20T pulley => 40 mm/rev. Positions are 40 mm apart.
static const int   PIN_STEP          = 25;
static const int   PIN_DIR           = 26;
static const int   PIN_ENABLE        = 27;
static const float STEPS_PER_REV     = 200.0;   // 1.8° NEMA 17
static const int   MICROSTEPPING     = 16;
static const float MM_PER_REV        = 40.0;    // GT2 20T
static const float POSITION_PITCH_MM = 40.0;    // distance between compartments
static const float MAX_MM_PER_SEC    = 120.0;
static const float ACCEL_MM_PER_S2   = 400.0;

// ---------------------------------------------------------------- homing ----
static const int   PIN_HOME_SWITCH   = 34;   // mechanical limit at position 1, NC
static const bool  HOME_SEEK_TOWARD_ZERO = true;
static const float HOME_BACKOFF_MM   = 3.0;
static const float HOMING_TIMEOUT_S  = 10.0;
static const float MOVE_TIMEOUT_S    = 6.0;

// --------------------------------------------------------------- load cell --
static const int   PIN_HX_DOUT       = 33;   // single carriage-mounted cell
static const int   PIN_HX_SCK        = 32;   // weighs the item IN the carriage
static const float LC_CALIBRATION    = 401.2f;  // units/kg
static const float MIN_DEPOSIT_G     = 1.0;

// ------------------------------------------------------------ fill sensors --
static const int   PIN_TOF_XSHUT[4]  = { 4, 13, 14, 15 };
static const uint8_t TOF_ADDR[4]     = { 0x2A, 0x2B, 0x2C, 0x2D };
static const float BIN_DEPTH_MM      = 250.0;

// ----------------------------------------------------------------- timing ---
static const uint32_t HEARTBEAT_MS   = 5000;

// ----------------------------------------------------------------- safety ---
static const float MAX_TRAVEL_MM     = 130.0;  // software limit switch
