#!/bin/sh
# Post-deployment smoke test: health, frontend, wrong and right credentials, one scenario.
# Needs only sh, curl, grep and sed (no Python on the agent).
# Usage: sh scripts/smoke_test.sh http://127.0.0.1:5000 supervisor <password>
set -e
BASE=${1:-http://127.0.0.1:5000}
USER=${2:-supervisor}
PASS=${3:?password required}

echo "Health:"
curl -fsS "$BASE/api/health"
echo
curl -fsS "$BASE/" | grep -q SKYCONTROL
echo "Frontend: OK"

CODE=$(curl -s -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USER\",\"password\":\"wrong-password-123\"}" "$BASE/api/auth/login")
[ "$CODE" = "401" ]
echo "Wrong credentials rejected: OK ($CODE)"

TOKEN=$(curl -fsS -H 'Content-Type: application/json' -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}" "$BASE/api/auth/login" \
  | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
[ -n "$TOKEN" ]
echo "Login with verified credentials: OK"

RUN=$(curl -fsS -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"scenario":"readback_error"}' "$BASE/api/lab/runs")
echo "$RUN" | grep -q '"plan_valid":true'
echo "Scenario lab: readback_error plan verified"

ATTEMPTS=$(curl -fsS -H "Authorization: Bearer $TOKEN" "$BASE/api/auth/attempts?failed_only=true")
echo "$ATTEMPTS" | grep -q '"reason":"wrong_password"'
echo "Failed login stored in the backend: OK"
echo "Smoke test passed"
