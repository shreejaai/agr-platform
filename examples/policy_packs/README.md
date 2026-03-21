# AGR Policy Packs

Pre-built governance policies for common AI agent use cases. Import one or more packs to get started quickly.

## Available Packs

| File | Policies | Use case |
|------|----------|----------|
| `finance_controls.yaml` | 6 | Payment approval, transfer limits, vendor checks |
| `devops_controls.yaml` | 5 | Production deploy gates, database protection |
| `data_access_controls.yaml` | 5 | PII export prevention, department scoping, read controls |
| `security_signals.yaml` | 4 | Prompt injection detection, geo anomaly, repeated denial signals |
| `starter_pack.yaml` | 20 | All packs combined — good starting point for any org |
| `starter_pack.json` | 20 | Same 20 policies in JSON format |

## Import via Curl

```bash
# Dry run first
bash ../curl/08_import_policies_yaml.sh
bash ../curl/09_import_policies_json.sh

# Commit for real
bash ../curl/08_import_policies_yaml.sh --commit
bash ../curl/09_import_policies_json.sh --commit
```

## Import via Python

```python
import json, httpx

policies = json.load(open("starter_pack.json"))["policies"]

httpx.post(
    "http://localhost:8000/v1/policies/import",
    headers={"Authorization": f"Bearer {AGR_API_KEY}"},
    json={"policies": policies, "dry_run": False, "overwrite": False},
)
```

## Import via Dashboard

1. Open [http://localhost:4200](http://localhost:4200)
2. Go to **Policies → Import**
3. Paste the JSON content from `starter_pack.json`
4. Review the dry-run preview and click **Import**

## Policy Format

All YAML packs follow this structure:

```yaml
policies:
  - name: unique-policy-name
    level: org
    cedar_rule: |
      forbid(principal, action == Action::"some_action", resource)
      when { context has some_field && context.some_field == "value" };
    active: true
```

## Notes

- Policies are evaluated using Cedar semantics: `forbid` takes precedence over `permit`.
- `level: org` means the policy applies to all agents in the org.
- Set `active: false` to import a policy in disabled state for review.
- Use `overwrite: true` in the import call to update existing policies with the same name.
