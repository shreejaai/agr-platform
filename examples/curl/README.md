# AGR Curl Examples

Raw HTTP examples using curl. Good for exploring the API or integrating AGR into shell-based CI pipelines.

## Prerequisites

- `curl` and `python3` installed
- AGR platform running: `docker compose up -d` from the repo root
- API key exported:
  ```bash
  export AGR_API_KEY="agr_sk_YOUR_KEY_HERE"
  ```

If you don't have an API key yet, run the setup script:
```bash
bash 00_setup.sh
# then copy the export line it prints
```

## Running Individual Scripts

Each script is self-contained. Run any of them directly:

```bash
bash 01_health_check.sh
bash 03_safe_read_allowed.sh
bash 05_transfer_funds_approval.sh
```

All scripts require `AGR_API_KEY` to be set (except `00_setup.sh` and `01_health_check.sh`).

## Running the Full Demo

```bash
bash 12_full_demo.sh
```

This runs scenarios 01–11 in sequence with colored output and prints a final PASS/FAIL summary.

## Script Reference

| Script | What it does |
|--------|-------------|
| `00_setup.sh` | Create a test org and print the API key |
| `01_health_check.sh` | GET /health — verify the daemon is up |
| `02_register_agent.sh` | Register a finance agent |
| `03_safe_read_allowed.sh` | Evaluate read_ticket_status → expect ALLOW |
| `04_deploy_prod_denied.sh` | Evaluate deploy on production → expect DENY |
| `05_transfer_funds_approval.sh` | Transfer $50K — full approve flow |
| `06_export_customer_db_denied.sh` | Export with injection score → expect DENY |
| `07_rate_limit_spam.sh` | 120 rapid requests — shows 200 vs 429 |
| `08_import_policies_yaml.sh` | Import finance_controls policies |
| `09_import_policies_json.sh` | Import starter_pack.json |
| `10_export_policies.sh` | Export all active policies |
| `11_verify_audit_chain.sh` | Verify tamper-evident audit log |
| `12_full_demo.sh` | Full end-to-end demo |

## Notes

- `AGR_BASE_URL` defaults to `http://localhost:8000`. Override to point at a remote instance.
- Scripts exit non-zero on any curl failure (`set -euo pipefail`).
- `07_rate_limit_spam.sh` only triggers HTTP 429 if `eval_limit` is set on your org. With `eval_limit=0` (unlimited) you will see all 200s.
