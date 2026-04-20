#!/usr/bin/env bash
# Run all service test suites and report combined coverage.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICES=("document-service" "auth-service" "notification-service" "api-gateway")
PASS=0
FAIL=0

run_tests() {
  local svc="$1"
  local dir="$ROOT/$svc"
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Testing: $svc"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  local env_vars=(
    "DATABASE_URL=sqlite+aiosqlite:///:memory:"
    "SECRET_KEY=test-secret-key-for-ci-only"
    "APP_NAME=$svc"
    "APP_VERSION=1.0.0"
    "RABBITMQ_URL=amqp://guest:guest@localhost:5672/"
    "REDIS_URL=redis://localhost:6379"
    "AUTH_SERVICE_URL=http://auth-service:8000"
    "DOCUMENT_SERVICE_URL=http://document-service:8000"
    "NOTIFICATION_SERVICE_URL=http://notification-service:8000"
  )

  # Detect python / pytest binary (venv-aware)
  local python_bin
  if [[ -f "$dir/venv/Scripts/pytest" ]]; then
    python_bin="$dir/venv/Scripts/pytest"
  elif [[ -f "$dir/venv/bin/pytest" ]]; then
    python_bin="$dir/venv/bin/pytest"
  else
    python_bin="pytest"
  fi

  if env "${env_vars[@]}" "$python_bin" "$dir/tests/" \
       -v --cov=src --cov-report=term-missing --cov-fail-under=80 \
       --rootdir="$dir"; then
    echo "  ✅ $svc — PASSED"
    PASS=$((PASS + 1))
  else
    echo "  ❌ $svc — FAILED"
    FAIL=$((FAIL + 1))
  fi
}

for svc in "${SERVICES[@]}"; do
  run_tests "$svc"
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Results: $PASS passed / $FAIL failed"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[[ $FAIL -eq 0 ]] || exit 1
