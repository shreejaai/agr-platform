"""Policy import/export demo — bulk-import a policy pack then export to verify.

Usage:
    AGR_API_KEY=agr_sk_... python 04_policy_import_export.py
"""

import os
import sys

import httpx

AGR_BASE_URL = os.environ.get("AGR_BASE_URL", "http://localhost:8000")
AGR_API_KEY = os.environ.get("AGR_API_KEY", "")

if not AGR_API_KEY:
    print("ERROR: Set AGR_API_KEY")
    sys.exit(1)

headers = {"Authorization": f"Bearer {AGR_API_KEY}"}

POLICIES = [
    {
        "name": "Demo: Allow staging reads",
        "level": "org",
        "cedar_rule": 'permit(principal, action == Action::"read", resource) when { context has environment && context.environment == "staging" };',
    },
    {
        "name": "Demo: Deny production drops",
        "level": "org",
        "cedar_rule": 'forbid(principal, action == Action::"db.drop", resource) when { context has environment && context.environment == "production" };',
    },
    {
        "name": "Demo: Require approval for prod deploy",
        "level": "org",
        "cedar_rule": 'forbid(principal, action == Action::"deploy", resource) when { context has environment && context.environment == "production" } unless { context has approval_status && context.approval_status == "approved" };',
    },
]

with httpx.Client(base_url=AGR_BASE_URL, headers=headers, timeout=10) as client:
    # Step 1: Dry run
    print("Step 1: Dry run validation...")
    r = client.post("/v1/policies/import", json={"policies": POLICIES, "dry_run": True})
    result = r.json()
    print(f"  Would create: {result['created']}, errors: {result['errors']}")
    for item in result["results"]:
        print(f"  [{item['status']:8s}] {item['name']}")

    # Step 2: Real import
    print("\nStep 2: Real import...")
    r = client.post(
        "/v1/policies/import", json={"policies": POLICIES, "overwrite": True}
    )
    result = r.json()
    print(f"  Created: {result['created']}, Updated: {result['updated']}, Errors: {result['errors']}")

    # Step 3: Export
    print("\nStep 3: Export all policies...")
    r = client.get("/v1/policies/export")
    export = r.json()
    print(f"  Total exported: {export['total']}")
    for p in export["policies"]:
        print(f"  [{p['level']:6s}] {p['name']}")
