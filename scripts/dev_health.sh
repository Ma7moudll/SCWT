#!/usr/bin/env bash
# =============================================================================
# dev_health.sh — health check for the COMPLETE REAL dev stack.
# Verifies: PostgreSQL, mosquitto, ai-service (REAL classifier), backend, and
# a real login + real prediction round-trip. Honest exit code (non-zero on
# any failure) — no silent fallback.
# =============================================================================
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv/bin/python"

MQTT_PORT="${MQTT_PORT:-1886}"
AI_PORT="${AI_PORT:-8052}"
API_PORT="${API_PORT:-8100}"

ok=0; fail=0
check() {  # check <name> <0|1>
  if [ "$2" -eq 0 ]; then echo "  [OK]   $1"; ok=$((ok+1));
  else echo "  [FAIL] $1"; fail=$((fail+1)); fi
}

echo "SCWT dev stack health:"

# 1. PostgreSQL
if PGPASSWORD=scwt psql -h localhost -U scwt -lqt 2>/dev/null | cut -d'|' -f1 | grep -q scwt; then
  check "PostgreSQL db scwt_db reachable" 0
else
  check "PostgreSQL db scwt_db reachable" 1
fi

# 2. mosquitto
nc -z 127.0.0.1 "$MQTT_PORT" 2>/dev/null; check "mosquitto :$MQTT_PORT" $?

# 3. ai-service
AI_HEALTH="$(curl -sS --max-time 5 "http://127.0.0.1:$AI_PORT/health" 2>/dev/null || true)"
if echo "$AI_HEALTH" | grep -q '"classifier": *"real"'; then
  check "ai-service :$AI_PORT classifier=real" 0
else
  check "ai-service :$AI_PORT classifier=real (got: $AI_HEALTH)" 1
fi

# 4. backend
BACKEND_HEALTH="$(curl -sS --max-time 5 "http://127.0.0.1:$API_PORT/health" 2>/dev/null || true)"
if echo "$BACKEND_HEALTH" | grep -q '"status":"ok"\|"status": "ok"'; then
  check "backend :$API_PORT /health" 0
else
  check "backend :$API_PORT /health (got: $BACKEND_HEALTH)" 1
fi

# 5. Real prediction round-trip via the backend -> real AI service.
if [ "$fail" -eq 0 ]; then
  FIXTURE="$ROOT/ai-service/tests/fixtures/high_conf_plastic.png"
  if [ -f "$FIXTURE" ]; then
    RESP="$(curl -sS --max-time 20 "http://127.0.0.1:$API_PORT/health" 2>/dev/null || true)"
    # Login requires a user; create a throwaway health user via register if none.
    TOKEN="$("$VENV" - "$API_PORT" <<'PY'
import json, sys, httpx
port = sys.argv[1]
c = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=20)
email = "health@scwt.campus"
r = c.post("/api/v1/auth/register", json={"name":"Health Probe","email":email,"password":"health123","facultyId":"ENGINEERING","studentCode":"S-HEALTH"})
# Registration creates the account only — an explicit login mints the session.
if r.status_code == 201 or r.status_code == 409:
    r = c.post("/api/v1/auth/login", json={"email":email,"password":"health123"})
if r.status_code != 200:
    sys.exit(1)
print(r.json()["token"])
PY
)"
    if [ -n "$TOKEN" ]; then
      PRED="$(curl -sS --max-time 20 "http://127.0.0.1:$API_PORT/api/v1/ai/predict" \
        -H "Authorization: Bearer $TOKEN" \
        -F "image=@$FIXTURE;type=image/png" 2>/dev/null || true)"
      if echo "$PRED" | grep -q '"source": *"ai"\|"source":"ai"'; then
        check "real AI round-trip (prediction source=ai)" 0
      else
        check "real AI round-trip (source=ai missing: ${PRED:0:120})" 1
      fi
    else
      check "register/login health user" 1
    fi
  else
    check "fixture $FIXTURE for round-trip" 1
  fi
fi

echo
echo "RESULT: $ok ok, $fail failed"
exit $((fail > 0))