"""AGR generic framework enforcer example.

Shows how to use the shared AGRPolicyEnforcer API to guard arbitrary tools
before execution without coupling to a specific framework.
"""

import os
from typing import Any

from agr import AGRClient, AGRPolicyEnforcer

API_KEY = os.environ.get("AGR_API_KEY", "agr_sk_YOUR_KEY_HERE")
BASE_URL = os.environ.get("AGR_BASE_URL", "http://localhost:8000")

agr = AGRClient(api_key=API_KEY, base_url=BASE_URL)
enforcer = AGRPolicyEnforcer(
    agr,
    agent_id="generic-framework-agent",
    default_context={"framework": "custom-orchestration"},
)


@enforcer.wrap(
    action="deploy",
    resource="production-cluster",
    context=lambda version: {"environment": "production", "release_version": version},
)
def deploy_release(version: str) -> str:
    return f"[mock deploy] Released version {version}"


def run_step(step: str, *args: Any) -> str:
    if step == "deploy":
        return deploy_release(*args)
    raise ValueError(f"Unknown step: {step}")


def main() -> None:
    print("=== AGR generic framework enforcer demo ===")
    try:
        result = run_step("deploy", "2026.03.27")
        print(result)
    except Exception as exc:
        print(f"Blocked by AGR: {exc}")


if __name__ == "__main__":
    main()
