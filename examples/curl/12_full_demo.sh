#!/usr/bin/env bash
set -euo pipefail

: "${AGR_API_KEY:?Set AGR_API_KEY first — see examples/curl/00_setup.sh}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASS=0
FAIL=0
declare -a RESULTS=()

run_scenario() {
  local num="$1"
  local label="$2"
  local script="$3"

  echo ""
  echo -e "${CYAN}══════════════════════════════════════════════${NC}"
  echo -e "${CYAN}  Scenario $num: $label${NC}"
  echo -e "${CYAN}══════════════════════════════════════════════${NC}"

  if bash "${SCRIPT_DIR}/${script}" 2>&1; then
    PASS=$((PASS + 1))
    RESULTS+=("${GREEN}PASS${NC}  $num $label")
  else
    FAIL=$((FAIL + 1))
    RESULTS+=("${RED}FAIL${NC}  $num $label")
  fi
}

echo -e "${YELLOW}╔══════════════════════════════════════════════╗${NC}"
echo -e "${YELLOW}║         AGR Full Demo — All Scenarios         ║${NC}"
echo -e "${YELLOW}╚══════════════════════════════════════════════╝${NC}"

run_scenario "01" "Health Check"                  "01_health_check.sh"
run_scenario "02" "Register Agent"                "02_register_agent.sh"
run_scenario "03" "Safe Read → ALLOW"             "03_safe_read_allowed.sh"
run_scenario "04" "Deploy Prod → DENY"            "04_deploy_prod_denied.sh"
run_scenario "05" "Transfer \$50K → Approval"     "05_transfer_funds_approval.sh"
run_scenario "06" "Export DB + Injection → DENY"  "06_export_customer_db_denied.sh"
run_scenario "07" "Rate Limit Stress Test"         "07_rate_limit_spam.sh"
run_scenario "08" "Import Finance Policies"        "08_import_policies_yaml.sh"
run_scenario "09" "Import Starter Pack JSON"       "09_import_policies_json.sh"
run_scenario "10" "Export Active Policies"         "10_export_policies.sh"
run_scenario "11" "Verify Audit Chain"             "11_verify_audit_chain.sh"

echo ""
echo -e "${YELLOW}╔══════════════════════════════════════════════╗${NC}"
echo -e "${YELLOW}║                 Final Summary                 ║${NC}"
echo -e "${YELLOW}╚══════════════════════════════════════════════╝${NC}"
for r in "${RESULTS[@]}"; do
  echo -e "  $r"
done
echo ""
echo -e "  Total: $((PASS + FAIL))  ${GREEN}PASS: $PASS${NC}  ${RED}FAIL: $FAIL${NC}"

if [ "$FAIL" -eq 0 ]; then
  echo ""
  echo -e "${GREEN}✅ All scenarios passed!${NC}"
  exit 0
else
  echo ""
  echo -e "${RED}❌ $FAIL scenario(s) failed.${NC}"
  exit 1
fi
