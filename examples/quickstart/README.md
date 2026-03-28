# AGR Quickstart

These examples assume the API is running locally on `http://localhost:8000` and your API key is available as `AGR_API_KEY`.

## Shell examples

```sh
bash examples/quickstart/01_evaluate.sh
bash examples/quickstart/02_simulate.sh
bash examples/quickstart/03_approval.sh
```

## Python SDK

```sh
python3 examples/quickstart/quickstart.py
```

## TypeScript SDK

```sh
npx tsx examples/quickstart/quickstart.ts
```

## Postman

Import `examples/quickstart/agr.postman_collection.json` and set:

- `base_url`
- `api_key`
