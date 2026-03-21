# AGR Node / TypeScript Examples

TypeScript examples using the AGR SDK.

## Prerequisites

- Node.js 18+
- AGR platform running: `docker compose up -d` from the repo root
- API key exported:
  ```bash
  export AGR_API_KEY="agr_sk_YOUR_KEY_HERE"
  ```

## Install

```bash
cd examples/node
npm install
```

## Running Examples

```bash
npx tsx 01_quickstart.ts
npx tsx 02_approval_flow.ts
npx tsx 03_import_policies.ts
```

## Script Reference

| Script | Description |
|--------|-------------|
| `01_quickstart.ts` | Evaluate and handle ALLOW / APPROVAL_REQUIRED / DENY |
| `02_approval_flow.ts` | Full approval lifecycle with auto-approve after 3s |
| `03_import_policies.ts` | Bulk policy import via /v1/policies/import |

## Notes

- `AGR_API_KEY` must be set before running any script.
- `AGR_BASE_URL` defaults to `http://localhost:8000`. Override to point at a remote instance:
  ```bash
  export AGR_BASE_URL="https://your-agr-instance.example.com"
  ```
- Examples use `tsx` to run TypeScript directly without a separate compile step.
