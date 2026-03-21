# AGR Platform — Examples

End-to-end examples showing how to integrate AGR governance into AI agent workflows.

## Prerequisites

1. Start the platform:
   ```bash
   docker compose up -d
   ```
2. Sign in at [http://localhost:4200](http://localhost:4200) and copy your API key.
3. Export the key:
   ```bash
   export AGR_API_KEY="agr_sk_YOUR_KEY_HERE"
   ```

## Quick Start (60 seconds)

```bash
# 1. Health check
curl -sf http://localhost:8000/health | python3 -m json.tool

# 2. Evaluate a safe action
curl -sX POST http://localhost:8000/v1/evaluate \
  -H "Authorization: Bearer $AGR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"demo-agent","action":"read_ticket_status","resource":"ticket-1","context":{}}' \
  | python3 -m json.tool

# 3. Evaluate a blocked action
curl -sX POST http://localhost:8000/v1/evaluate \
  -H "Authorization: Bearer $AGR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"ci-agent","action":"deploy","resource":"prod","context":{"environment":"production"}}' \
  | python3 -m json.tool

# 4. Verify audit chain integrity
curl -sf http://localhost:8000/v1/audit/verify \
  -H "Authorization: Bearer $AGR_API_KEY" | python3 -m json.tool
```

## All Scenarios

| # | Scenario | Decision | Script |
|---|----------|----------|--------|
| 01 | Health check | — | `curl/01_health_check.sh` |
| 02 | Register agent | — | `curl/02_register_agent.sh` |
| 03 | Safe read → ALLOW | ALLOW | `curl/03_safe_read_allowed.sh` |
| 04 | Deploy to production → DENY | DENY | `curl/04_deploy_prod_denied.sh` |
| 05 | Transfer $50K → APPROVAL_REQUIRED | APPROVAL_REQUIRED | `curl/05_transfer_funds_approval.sh` |
| 06 | Export customer DB → DENY | DENY | `curl/06_export_customer_db_denied.sh` |
| 07 | Rate limit stress test | 200 / 429 | `curl/07_rate_limit_spam.sh` |
| 08 | Import finance policies (YAML) | — | `curl/08_import_policies_yaml.sh` |
| 09 | Import starter pack (JSON) | — | `curl/09_import_policies_json.sh` |
| 10 | Export active policies | — | `curl/10_export_policies.sh` |
| 11 | Verify audit chain | valid | `curl/11_verify_audit_chain.sh` |
| 12 | Full demo (01–11 in sequence) | — | `curl/12_full_demo.sh` |

## Policy Packs

Pre-built policy bundles in `policy_packs/`. Import them via curl, Python, or the dashboard.

| File | Policies | Use case |
|------|----------|----------|
| `finance_controls.yaml` | 6 | Payment approval, transfer limits, vendor checks |
| `devops_controls.yaml` | 5 | Production deploy gates, database protection |
| `data_access_controls.yaml` | 5 | PII export, department scoping, read controls |
| `security_signals.yaml` | 4 | Prompt injection, geo anomaly, repeated denials |
| `starter_pack.yaml` | 20 | All of the above combined |
| `starter_pack.json` | 20 | JSON format for programmatic import |

See [policy_packs/README.md](policy_packs/README.md) for import instructions.

## Python Examples

```bash
cd examples/python
pip install -r requirements.txt
python 01_quickstart.py
```

| Script | Description |
|--------|-------------|
| `01_quickstart.py` | Protect any tool call in 3 lines |
| `02_approval_flow.py` | Full approval lifecycle with auto-approve |
| `03_langgraph_agent.py` | Wrap a LangGraph tool with governance |
| `04_crewai_agent.py` | CrewAI-style AGRToolWrapper pattern |
| `05_import_policies.py` | Bulk policy import with dry-run preview |
| `06_risk_score_demo.py` | 5 scenarios showing risk score escalation |
| `07_full_scenario_test.py` | Automated pass/fail test suite |

See [python/README.md](python/README.md).

## Node / TypeScript Examples

```bash
cd examples/node
npm install
npx tsx 01_quickstart.ts
```

| Script | Description |
|--------|-------------|
| `01_quickstart.ts` | Evaluate and handle ALLOW / APPROVAL / DENY |
| `02_approval_flow.ts` | Full approval lifecycle in TypeScript |
| `03_import_policies.ts` | Bulk policy import via fetch |

See [node/README.md](node/README.md).

## Curl Examples

```bash
cd examples/curl
bash 01_health_check.sh
bash 12_full_demo.sh   # runs everything
```

See [curl/README.md](curl/README.md).
