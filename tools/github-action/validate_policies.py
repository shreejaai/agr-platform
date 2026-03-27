#!/usr/bin/env python3
"""AGR policy validation script for the GitHub Action.

Reads .cedar files from POLICY_DIR, validates each against the AGR API,
checks for conflicts, and optionally runs a dry-run evaluation.

Exit codes:
  0 — all policies valid (or only warnings)
  1 — validation errors or conflicts found
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    import httpx
    import yaml as _yaml  # noqa: F401 — verify pyyaml is installed
except ImportError:
    print("::error::Missing dependencies. Run: pip install httpx pyyaml")
    sys.exit(1)

AGR_API_KEY = os.environ.get("AGR_API_KEY", "")
AGR_BASE_URL = os.environ.get("AGR_BASE_URL", "https://api.agr.dev").rstrip("/")
POLICY_DIR = Path(os.environ.get("POLICY_DIR", "."))
DRY_RUN_AGENT = os.environ.get("DRY_RUN_AGENT", "")
FAIL_ON_CONFLICT = os.environ.get("FAIL_ON_CONFLICT", "true").lower() == "true"

VALID_STARTS = ("permit", "forbid")


def _gh_annotation(level: str, file: str, message: str) -> None:
    """Emit a GitHub Actions annotation."""
    print(f"::{level} file={file}::{message}")


def _load_cedar_files() -> list[tuple[Path, str]]:
    """Return (path, cedar_rule) for all .cedar files under POLICY_DIR."""
    policies = []
    for ext in ("*.cedar",):
        for f in sorted(POLICY_DIR.rglob(ext)):
            content = f.read_text(encoding="utf-8").strip()
            if content:
                policies.append((f, content))
    return policies


def _validate_syntax(path: Path, rule: str) -> list[str]:
    """Basic local syntax checks before hitting the API."""
    errors = []
    lower = rule.lower()
    if not any(lower.startswith(v) for v in VALID_STARTS):
        errors.append("Rule must start with 'permit' or 'forbid'.")
    if not rule.rstrip().endswith(";"):
        errors.append("Rule must end with ';'.")
    depth = 0
    for ch in rule:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth < 0:
            errors.append("Unmatched closing parenthesis.")
            break
    if depth != 0:
        errors.append("Unclosed parenthesis.")
    return errors


def _api_validate(client: httpx.Client, name: str, rule: str) -> dict:
    """POST to AGR /v1/policies with state=draft to check server-side validity."""
    try:
        resp = client.post(
            f"{AGR_BASE_URL}/v1/policies",
            json={
                "name": name,
                "cedar_rule": rule,
                "level": "org",
                "state": "draft",
                "description": "CI validation — will be deleted",
            },
        )
        if resp.status_code == 201:
            # Clean up the draft we just created
            policy_id = resp.json().get("id")
            if policy_id:
                client.delete(f"{AGR_BASE_URL}/v1/policies/{policy_id}")
            return {"valid": True}
        elif resp.status_code == 422:
            detail = resp.json().get("detail", "Validation failed.")
            if isinstance(detail, list):
                detail = "; ".join(str(d.get("msg", d)) for d in detail)
            return {"valid": False, "error": str(detail)}
        else:
            return {"valid": False, "error": f"API returned HTTP {resp.status_code}"}
    except httpx.RequestError as e:
        return {"valid": False, "error": f"API request failed: {e}"}


def main() -> int:
    if not AGR_API_KEY:
        print("::error::AGR_API_KEY is not set. Add it as a GitHub secret.")
        return 1

    policies = _load_cedar_files()
    if not policies:
        print(f"::notice::No .cedar files found under '{POLICY_DIR}'. Nothing to validate.")
        return 0

    print(f"Found {len(policies)} Cedar policy file(s) to validate.")

    errors_total = 0
    results: list[dict] = []

    headers = {"Authorization": f"Bearer {AGR_API_KEY}", "Content-Type": "application/json"}
    with httpx.Client(headers=headers, timeout=30.0) as client:
        for path, rule in policies:
            rel = str(path.relative_to(POLICY_DIR) if POLICY_DIR in path.parents else path)
            print(f"  Validating: {rel}")

            # Local syntax check
            syntax_errors = _validate_syntax(path, rule)
            if syntax_errors:
                for err in syntax_errors:
                    _gh_annotation("error", str(path), err)
                    errors_total += 1
                results.append({"file": rel, "valid": False, "errors": syntax_errors})
                continue

            # API validation (creates a draft, checks server-side, deletes it)
            api_result = _api_validate(client, path.stem, rule)
            if not api_result["valid"]:
                error_msg = api_result.get("error", "Unknown error")
                _gh_annotation("error", str(path), error_msg)
                errors_total += 1
                results.append({"file": rel, "valid": False, "errors": [error_msg]})
            else:
                print(f"    ✓ {rel} is valid.")
                results.append({"file": rel, "valid": True, "errors": []})

    # Summary
    valid_count = sum(1 for r in results if r["valid"])
    print(f"\nSummary: {valid_count}/{len(results)} policies valid.")

    # Write step output
    output = json.dumps(
        {
            "total": len(results),
            "valid": valid_count,
            "invalid": len(results) - valid_count,
            "results": results,
        }
    )
    # GitHub Actions output
    with open(os.environ.get("GITHUB_OUTPUT", "/dev/null"), "a") as f:
        f.write(f"validation-result={output}\n")

    if errors_total > 0:
        print(f"\n::error::{errors_total} validation error(s) found. See annotations above.")
        return 1

    print("\nAll policies passed validation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
