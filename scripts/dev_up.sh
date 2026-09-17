#!/usr/bin/env bash
# =============================================================================
# dev_up.sh — start the COMPLETE REAL development stack (no demo, no mocks).
#
#   * PostgreSQL        (local, role scwt/scwt, db scwt_db)
#   * mosquitto broker  (port 1886 — SCWT owns this port)
#   * ai-service        (port 8052 — REAL ONNX classifier, gate enabled)
#   * backend           (port 8100 — FastAPI + Postgres, MQTT -> broker,
#                        AI -> ai-service, config-only seed: NO demo user)
#
# Use with the mobile app:
#   flutter run --dart-define=SCWT_MODE=production \
#               --dart-define=API_BASE_URL=http://10.0.2.2:8100/api/v1
#
# Physical events come from the hardware simulator (hardware-simulator/, the
# future ESP32). This stack never writes demo rows.
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv/bin/python"
MOSQUITTO_BIN="${MOSQUITTO_BIN:-/opt/homebrew/sbin/mosquitto}"
AI_MODEL="$ROOT/ai-service/models/model.onnx"

MQTT_PORT="${MQTT_PORT:-1886}"
AI_PORT="${AI_PORT:-8052}"
API_PORT="${API_PORT:-8100}"

# --- preconditions -----------------------------------------------------------
[ -x "$MOSQUITTO_BIN" ] || { echo "FATAL: mosquitto not found at $MOSQUITTO_BIN"; exit 1; }
[ -f "$AI_MODEL" ] || { echo "FATAL: trained model not found at $AI_MODEL"; exit 1; }
PGPASSWORD=scwt psql -h localhost -U scwt -lqt 2>/dev/null | cut -d'|' -f1 | grep -q scwt_db \
  || { echo "FATAL: db scwt_db missing — start Postgres and create it"; exit 1; }

port_in_use() { nc -z 127.0.0.1 "$1" 2>/dev/null; }

is_service_up() {
  local port="$1" name="$2"
  if port_in_use "$port"; then
    local pid; pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1 || true)"
    if [ -n "$pid" ]; then
      echo "[dev_up] $name already running on :$port (pid $pid) — leaving it"
      return 0
    fi
  fi
  return 1
}

# --- start each service (skips ones already up) -------------------------------
# The local broker is AUTHENTICATED even in development (parity with prod):
# a per-run random password is generated for the `backend` identity and
# exported to the backend/simulator via env. Never written to the repo.
MQTT_DEV_USER="backend"
PASSWD_FILE="$ROOT/.dev-mosquitto.passwd"
ACL_FILE="$ROOT/.dev-mosquitto.acl"

if is_service_up "$MQTT_PORT" "mosquitto"; then
  # Broker already up: credentials must come from the caller's environment.
  MQTT_DEV_PASS="${MQTT_PASSWORD:-}"
  if [ -z "$MQTT_DEV_PASS" ]; then
    echo "FATAL: broker already running but MQTT_PASSWORD is not set."
    echo "       Export MQTT_PASSWORD before running dev_up.sh, or stop the existing broker."
    exit 1
  fi
else
  MQTT_DEV_PASS="$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')"
  echo "[dev_up] starting mosquitto on :$MQTT_PORT (authenticated)"
  command -v mosquitto_passwd >/dev/null || { echo "FATAL: mosquitto_passwd not found"; exit 1; }
  rm -f "$PASSWD_FILE"
  mosquitto_passwd -b -c "$PASSWD_FILE" "$MQTT_DEV_USER" "$MQTT_DEV_PASS" >/dev/null
  cat > "$ACL_FILE" <<EOF2
user $MQTT_DEV_USER
topic readwrite scwt/stations/#
EOF2
  CONF="$(mktemp)"
  trap "rm -f '$CONF'" EXIT
  cat > "$CONF" <<EOF2
listener $MQTT_PORT 127.0.0.1
allow_anonymous false
password_file $PASSWD_FILE
acl_file $ACL_FILE
max_queued_messages 1000
message_size_limit 0
EOF2
  "$MOSQUITTO_BIN" -c "$CONF" -v > "$ROOT/.dev-mosquitto.log" 2>&1 &
  for _ in $(seq 1 30); do port_in_use "$MQTT_PORT" && break; sleep 0.2; done
fi

if is_service_up "$AI_PORT" "ai-service"; then :; else
  echo "[dev_up] starting ai-service (REAL classifier) on :$AI_PORT"
  PYTHONPATH="$ROOT/ai-service" \
  AI_SERVICE_CLASSIFIER=real \
  AI_MODEL_PATH="$AI_MODEL" \
  "$VENV" -m uvicorn app.main:app --host 127.0.0.1 --port "$AI_PORT" --log-level info \
    > "$ROOT/.dev-ai.log" 2>&1 &
  for _ in $(seq 1 60); do port_in_use "$AI_PORT" && break; sleep 0.3; done
fi

if is_service_up "$API_PORT" "backend"; then :; else
  echo "[dev_up] starting backend on :$API_PORT (config-only seed, no demo user)"
  # Stable strong dev JWT secret: generated once, reused across restarts so
  # student sessions survive. Override by exporting JWT_SECRET. NEVER committed.
  if [ -z "${JWT_SECRET:-}" ]; then
    JWT_FILE="$ROOT/.dev-jwt-secret"
    if [ ! -f "$JWT_FILE" ]; then
      "$VENV" -c 'import secrets; print(secrets.token_hex(32))' > "$JWT_FILE"
      chmod 600 "$JWT_FILE"
    fi
    JWT_SECRET="$(cat "$JWT_FILE")"
  fi
  PYTHONPATH="$ROOT/backend" \
  DATABASE_URL="postgresql+psycopg2://scwt:scwt@localhost:5432/scwt_db" \
  MQTT_BROKER_HOST=127.0.0.1 \
  MQTT_BROKER_PORT="$MQTT_PORT" \
  MQTT_USERNAME="$MQTT_DEV_USER" \
  MQTT_PASSWORD="$MQTT_DEV_PASS" \
  AI_SERVICE_URL="http://127.0.0.1:$AI_PORT" \
  JWT_SECRET="$JWT_SECRET" \
  SEED_ON_STARTUP=true \
  SEED_DEMO_USER=false \
  "$VENV" -m uvicorn app.main:app --host 0.0.0.0 --port "$API_PORT" --log-level info \
    > "$ROOT/.dev-backend.log" 2>&1 &
  for _ in $(seq 1 60); do port_in_use "$API_PORT" && break; sleep 0.3; done
fi

echo
echo "SCWT dev stack:"
echo "  mosquitto   :$MQTT_PORT  (log .dev-mosquitto.log)"
echo "  ai-service  :$AI_PORT   real classifier (log .dev-ai.log)"
echo "  backend     :$API_PORT   (log .dev-backend.log)"
echo
echo "Verify with:  scripts/dev_health.sh"
