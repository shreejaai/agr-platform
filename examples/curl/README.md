# AGR Platform — curl Examples

## Setup

```bash
export AGR_API_KEY=agr_sk_yourkey
export AGR_BASE_URL=http://localhost:8000   # or your deployed URL
```

## Scripts

| Script | Description |
|--------|-------------|
| `00_setup.sh` | Headless org creation |
| `01_health_check.sh` | Health check |
| `02_register_agent.sh` | Agent registration |
| `03_safe_read_allowed.sh` | ALLOW scenario |
| `04_deploy_prod_denied.sh` | DENY scenario |
| `05_transfer_funds_approval.sh` | APPROVAL_REQUIRED lifecycle |
| `06_export_customer_db_denied.sh` | Banned action DENY |
| `07_rate_limit_spam.sh` | Rate limiting |
| `08_import_policies_yaml.sh` | YAML policy import |
| `09_import_policies_json.sh` | JSON policy import |
| `10_export_policies.sh` | Policy export |
| `11_verify_audit_chain.sh` | Audit chain verification |
| `12_full_demo.sh` | Runs all scenarios end-to-end |

## Run any script

```bash
bash 03_safe_read_allowed.sh
```

## Run full demo

```bash
bash 12_full_demo.sh
```
