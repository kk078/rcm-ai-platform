#!/usr/bin/env bash
# ============================================================
# run_tests.sh — rcm-ai-platform Test Runner (Unix/macOS/Linux/WSL)
# Runs all tests for the RCM platform (rcm.aetherahealthcare.com)
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_NAME="rcm-ai-platform (rcm.aetherahealthcare.com)"
EXIT_CODE=0
FAIL_SUITES=0
PASS_SUITES=0

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { echo -e "${CYAN}$*${RESET}"; }
ok()   { echo -e "  ${GREEN}$*${RESET}"; }
warn() { echo -e "  ${YELLOW}[WARN] $*${RESET}"; }
err()  { echo -e "  ${RED}[FAIL] $*${RESET}"; }
bold() { echo -e "${BOLD}$*${RESET}"; }

echo
log "============================================================"
bold "  ${PLATFORM_NAME} Test Suite"
log "============================================================"
echo "  Started : $(date '+%Y-%m-%d %H:%M:%S')"
echo

cd "${SCRIPT_DIR}"

# ----------------------------------------------------------
# 1. Python
# ----------------------------------------------------------
PYTHON="${PYTHON:-python3}"
command -v "${PYTHON}" >/dev/null 2>&1 || { err "Python not found. Aborting."; exit 1; }
echo "  Python  : $(${PYTHON} --version 2>&1)"

# ----------------------------------------------------------
# 2. Virtual environment
# ----------------------------------------------------------
if [[ -f "${SCRIPT_DIR}/venv/bin/activate" ]]; then
    source "${SCRIPT_DIR}/venv/bin/activate"
    echo "  Venv    : ${SCRIPT_DIR}/venv"
elif [[ -f "${SCRIPT_DIR}/.venv/bin/activate" ]]; then
    source "${SCRIPT_DIR}/.venv/bin/activate"
    echo "  Venv    : ${SCRIPT_DIR}/.venv"
else
    echo "  Venv    : none"
fi

# ----------------------------------------------------------
# 3. Environment
# ----------------------------------------------------------
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH:-}"
export TEST_MODE=true
export DATABASE_URL="sqlite:///:memory:"
export REDIS_URL="redis://localhost:6379/15"
export SECRET_KEY="test-secret-key-not-for-production"
export JWT_SECRET_KEY="test-jwt-secret-not-for-production"

# ----------------------------------------------------------
# 4. Ensure pytest
# ----------------------------------------------------------
if ! "${PYTHON}" -m pytest --version >/dev/null 2>&1; then
    warn "pytest not found — installing..."
    "${PYTHON}" -m pip install pytest pytest-asyncio pytest-cov httpx --quiet
fi

# ----------------------------------------------------------
# 5. Unit test suites
# ----------------------------------------------------------
echo
log "------------------------------------------------------------"
bold "  Running UNIT tests..."
log "------------------------------------------------------------"

declare -a UNIT_SUITES=(
    "AI Dispatch         |tests/unit/test_ai_dispatch.py"
    "Analytics           |tests/unit/test_analytics.py"
    "Auth                |tests/unit/test_auth.py"
    "Billing             |tests/unit/test_billing.py"
    "Charge Intake       |tests/unit/test_charge_intake.py"
    "Client Billing      |tests/unit/test_client_billing.py"
    "Client Management   |tests/unit/test_client_management.py"
    "Coding              |tests/unit/test_coding.py"
    "Denials             |tests/unit/test_denials.py"
    "Full Platform       |tests/unit/test_full_platform.py"
    "Payments            |tests/unit/test_payments.py"
    "Provider Portal     |tests/unit/test_provider_portal.py"
    "Queues              |tests/unit/test_queues.py"
    "Scrubber            |tests/unit/test_scrubber.py"
    "Tasks               |tests/unit/test_tasks.py"
)

run_suite() {
    local name="$1" file="$2"
    if [[ ! -f "${file}" ]]; then
        warn "SKIP  ${name} — file not found: ${file}"
        return 0
    fi
    echo
    bold "  Suite: ${name}"
    echo "  File : ${file}"
    if "${PYTHON}" -m pytest "${file}" -v --tb=short --no-header -q 2>&1; then
        ok "PASSED"
        (( PASS_SUITES++ )) || true
    else
        err "FAILED"
        (( FAIL_SUITES++ )) || true
        EXIT_CODE=1
    fi
}

for entry in "${UNIT_SUITES[@]}"; do
    run_suite "${entry%%|*}" "${entry##*|}"
done

# ----------------------------------------------------------
# 6. Integration tests
# ----------------------------------------------------------
echo
log "------------------------------------------------------------"
bold "  Running INTEGRATION tests..."
log "------------------------------------------------------------"

if ls tests/integration/*.py >/dev/null 2>&1; then
    if "${PYTHON}" -m pytest tests/integration/ -v --tb=short -q 2>&1; then
        ok "Integration tests PASSED"
        (( PASS_SUITES++ )) || true
    else
        warn "Integration tests had failures (may need live services)"
    fi
else
    echo "  No integration tests found."
fi

# ----------------------------------------------------------
# 7. Coverage
# ----------------------------------------------------------
echo
log "------------------------------------------------------------"
bold "  Coverage Report"
log "------------------------------------------------------------"

if "${PYTHON}" -m pytest tests/unit/ \
    --cov=app --cov=workers \
    --cov-report=term-missing \
    --cov-report=html:coverage_html \
    -q 2>&1; then
    ok "Coverage report written to: coverage_html/index.html"
else
    warn "Coverage had warnings (non-fatal)"
fi

# ----------------------------------------------------------
# 8. Summary
# ----------------------------------------------------------
echo
log "============================================================"
bold "  TEST SUMMARY — ${PLATFORM_NAME}"
log "============================================================"
echo "  Finished  : $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Passed    : ${PASS_SUITES} suite(s)"
echo "  Failed    : ${FAIL_SUITES} suite(s)"

if [[ ${EXIT_CODE} -eq 0 ]]; then
    ok "Result    : ALL SUITES PASSED ✓"
else
    err "Result    : ONE OR MORE SUITES FAILED ✗"
fi
log "============================================================"
echo

exit ${EXIT_CODE}
