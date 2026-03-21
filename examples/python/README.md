# AGR Python Examples

Python examples using the AGR SDK.

## Prerequisites

- Python 3.10+
- AGR platform running: `docker compose up -d` from the repo root
- API key exported:
  ```bash
  export AGR_API_KEY="agr_sk_YOUR_KEY_HERE"
  ```

## Install

```bash
cd examples/python
pip install -r requirements.txt
```

## Running Examples

Each script is standalone:

```bash
python 01_quickstart.py
python 02_approval_flow.py
python 03_langgraph_agent.py
python 04_crewai_agent.py
python 05_import_policies.py
python 06_risk_score_demo.py
python 07_full_scenario_test.py
```

## Script Reference

| Script | Description |
|--------|-------------|
| `01_quickstart.py` | Protect any AI agent tool call in 3 lines — ALLOW, APPROVAL, DENY paths |
| `02_approval_flow.py` | Full approval lifecycle with background auto-approve thread |
| `03_langgraph_agent.py` | Wrap a LangGraph-style tool with AGR governance |
| `04_crewai_agent.py` | AGRToolWrapper pattern for CrewAI-style agents |
| `05_import_policies.py` | Bulk policy import with dry-run preview |
| `06_risk_score_demo.py` | 5 scenarios showing risk score escalation |
| `07_full_scenario_test.py` | Automated pass/fail test suite (exit 0 = all pass) |

## Notes

- All scripts read `AGR_API_KEY` from the environment. Set it before running.
- `AGR_BASE_URL` defaults to `http://localhost:8000`. Override to point at a remote instance:
  ```bash
  export AGR_BASE_URL="https://your-agr-instance.example.com"
  ```
- `07_full_scenario_test.py` exits with code 0 if all tests pass, 1 if any fail.
