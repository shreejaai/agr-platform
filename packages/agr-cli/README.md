# AGR CLI

Lightweight command line interface for the AGR platform.

## Install

```bash
pip install -e ../agr-sdk-python
pip install -e .
```

## Usage

```bash
export AGR_API_KEY=agr_sk_your_key_here
export AGR_BASE_URL=http://localhost:8000

agr eval \
  --agent deploy-bot \
  --action deploy \
  --resource production-cluster \
  --context '{"environment":"production"}'

agr simulate \
  --agent finance-bot \
  --action transfer_funds \
  --resource treasury-system \
  --context '{"amount":50000,"currency":"USD"}'

agr policy apply \
  --file ../../examples/policy_packs/devops_controls.yaml \
  --dry-run
```
