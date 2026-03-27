"""Cedar policy evaluation engine.

Primary: cedar-policy CLI via subprocess (if `cedar` binary is on PATH).
Fallback: Python regex evaluator for dev/CI without cedar CLI installed.

Decision values: "ALLOW" | "DENY" | "APPROVAL_REQUIRED"

APPROVAL_REQUIRED detection (both paths):
  A `forbid ... unless { context.approval_status == "approved" }` pattern means the
  action requires human sign-off. Detected by:
    1. First eval with given context → DENY
    2. Re-eval with approval_status="approved" injected → if ALLOW, return APPROVAL_REQUIRED
"""

import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    decision: str  # "ALLOW" | "DENY" | "APPROVAL_REQUIRED"
    reason: str
    policy_id: str | None
    requires_approval: bool
    latency_ms: float
    policy_source: str = "python_fallback"  # "cedar_cli" | "python_fallback" | "no_policies"
    # Explicit fallback tracking — always populated so callers can audit the engine path.
    fallback_used: bool = False
    fallback_reason: str | None = None  # reason Cedar CLI was not used (if fallback_used)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def evaluate_policies(
    cedar_policies: list[dict[str, str]],
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object],
) -> EvaluationResult:
    """Evaluate Cedar policies against a request.

    Tries the cedar CLI subprocess first; falls back to Python evaluator.
    Each policy dict must have keys: id, cedar_rule.
    """
    start = time.perf_counter_ns()

    if not cedar_policies:
        # L6: warn so ops can distinguish "no policies seeded yet" from silent deny
        logger.warning(
            "No active policies found for org — all actions will be DENY. "
            "Seed default policies or create at least one policy to allow actions."
        )
        elapsed = (time.perf_counter_ns() - start) / 1_000_000
        return EvaluationResult(
            decision="DENY",
            reason="No active policies found. All actions are denied by default.",
            policy_id=None,
            requires_approval=False,
            latency_ms=elapsed,
            policy_source="no_policies",
            fallback_used=False,
        )

    cedar_binary = _find_cedar_cli()
    if cedar_binary:
        try:
            result = _cedar_cli_evaluator(
                cedar_binary, cedar_policies, agent_id, action, resource, context
            )
            result.latency_ms = (time.perf_counter_ns() - start) / 1_000_000
            result.fallback_used = False
            return result
        except Exception as exc:
            fallback_reason = f"cedar_cli_error: {exc}"
            logger.warning(
                "Cedar CLI evaluation failed — using Python fallback. "
                "fallback_reason=%r agent_id=%r action=%r resource=%r",
                fallback_reason,
                agent_id,
                action,
                resource,
            )
            result = _python_evaluator(cedar_policies, agent_id, action, resource, context)
            result.latency_ms = (time.perf_counter_ns() - start) / 1_000_000
            result.fallback_used = True
            result.fallback_reason = fallback_reason
            return result

    fallback_reason = "cedar_cli_not_found"
    logger.debug(
        "Cedar CLI not on PATH — using Python fallback. "
        "Install cedar-policy-cli for authoritative enforcement. "
        "fallback_reason=%r",
        fallback_reason,
    )
    result = _python_evaluator(cedar_policies, agent_id, action, resource, context)
    result.latency_ms = (time.perf_counter_ns() - start) / 1_000_000
    result.fallback_used = True
    result.fallback_reason = fallback_reason
    return result


# ---------------------------------------------------------------------------
# Cedar CLI subprocess path
# ---------------------------------------------------------------------------


def _find_cedar_cli() -> str | None:
    """Return path to the cedar binary, or None if not installed."""
    return shutil.which("cedar")


def _cedar_cli_authorize(
    cedar_binary: str,
    policies: list[dict[str, str]],
    agent_id: str,
    action: str,
    resource_id: str,
    context: dict[str, object],
) -> str:
    """Run `cedar authorize` and return 'ALLOW' or 'DENY'. Raises on error."""
    policy_text = "\n\n".join(p["cedar_rule"] for p in policies)

    # Context dict doubles as resource attributes so `resource.X` conditions work.
    # This mirrors the Python evaluator which checks both `resource.X` and `context.X`
    # from the same context dict.
    entities = [
        {"uid": {"type": "Agent", "id": agent_id}, "attrs": {}, "parents": []},
        {
            "uid": {"type": "Resource", "id": resource_id},
            "attrs": {k: v for k, v in context.items() if v is not None},
            "parents": [],
        },
    ]

    request = {
        "principal": {"type": "Agent", "id": agent_id},
        "action": {"type": "Action", "id": action},
        "resource": {"type": "Resource", "id": resource_id},
        "context": context,
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        policies_path = Path(tmpdir) / "policies.cedar"
        entities_path = Path(tmpdir) / "entities.json"
        request_path = Path(tmpdir) / "request.cedarauth.json"
        policies_path.write_text(policy_text, encoding="utf-8")
        entities_path.write_text(json.dumps(entities), encoding="utf-8")
        request_path.write_text(json.dumps(request), encoding="utf-8")

        proc = subprocess.run(
            [
                cedar_binary,
                "authorize",
                "--policies",
                str(policies_path),
                "--entities",
                str(entities_path),
                "--request-json",
                str(request_path),
            ],
            capture_output=True,
            text=True,
            timeout=5.0,
        )

    output = proc.stdout.strip()
    for line in output.splitlines():
        stripped = line.strip()
        if stripped == "ALLOW" or stripped.startswith("Decision: ALLOW"):
            return "ALLOW"
        if stripped == "DENY" or stripped.startswith("Decision: DENY"):
            return "DENY"
    raise RuntimeError(
        f"Unexpected cedar output: stdout={proc.stdout!r} stderr={proc.stderr!r} "
        f"exit={proc.returncode}"
    )


def _cedar_cli_evaluator(
    cedar_binary: str,
    policies: list[dict[str, str]],
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object],
) -> EvaluationResult:
    """Evaluate using Cedar CLI with APPROVAL_REQUIRED detection via double-eval."""
    decision = _cedar_cli_authorize(cedar_binary, policies, agent_id, action, resource, context)

    if decision == "ALLOW":
        return EvaluationResult(
            decision="ALLOW",
            reason=f"Action '{action}' on '{resource}' is allowed by policy.",
            policy_id=None,  # Cedar CLI does not report which policy matched
            requires_approval=False,
            latency_ms=0,
            policy_source="cedar_cli",
        )

    # DENY — check if injecting approval_status=approved flips it to ALLOW.
    # If yes, a forbid...unless pattern is in play → APPROVAL_REQUIRED.
    if "approval_status" not in context:
        ctx_approved = {**context, "approval_status": "approved"}
        try:
            with_approval = _cedar_cli_authorize(
                cedar_binary, policies, agent_id, action, resource, ctx_approved
            )
            if with_approval == "ALLOW":
                return EvaluationResult(
                    decision="APPROVAL_REQUIRED",
                    reason=f"Action '{action}' on '{resource}' requires human approval.",
                    policy_id=None,
                    requires_approval=True,
                    latency_ms=0,
                    policy_source="cedar_cli",
                )
        except Exception as exc:
            logger.warning("Cedar CLI second-pass (approval check) failed: %s", exc)

    return EvaluationResult(
        decision="DENY",
        reason=f"Action '{action}' on '{resource}' is denied by policy.",
        policy_id=None,
        requires_approval=False,
        latency_ms=0,
        policy_source="cedar_cli",
    )


# ---------------------------------------------------------------------------
# Python regex fallback evaluator
# ---------------------------------------------------------------------------


def _python_evaluator(
    policies: list[dict[str, str]],
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object],
) -> EvaluationResult:
    """Python-based Cedar evaluator for dev/CI without cedar CLI.

    Parses forbid/permit rules and evaluates them.
    Forbid takes precedence over permit (deny-overrides).
    policy_id is populated (unlike the Cedar CLI path).
    """
    forbid_match: dict[str, str] | None = None
    permit_match: dict[str, str] | None = None
    approval_required = False

    for policy in policies:
        rule = policy["cedar_rule"]
        is_forbid = "forbid(" in rule
        is_permit = "permit(" in rule

        if not is_forbid and not is_permit:
            continue

        if _matches_rule(rule, agent_id, action, resource, context):
            if is_forbid:
                has_unless_approval = "approval_status" in rule and "unless" in rule
                if has_unless_approval:
                    approval_status = context.get("approval_status")
                    if approval_status == "approved":
                        permit_match = policy
                        continue
                    approval_required = True
                    forbid_match = policy
                else:
                    forbid_match = policy
            elif is_permit:
                permit_match = policy

    if forbid_match:
        if approval_required:
            return EvaluationResult(
                decision="APPROVAL_REQUIRED",
                reason=f"Action '{action}' on '{resource}' requires human approval.",
                policy_id=forbid_match["id"],
                requires_approval=True,
                latency_ms=0,
            )
        return EvaluationResult(
            decision="DENY",
            reason=f"Action '{action}' on '{resource}' is denied by policy.",
            policy_id=forbid_match["id"],
            requires_approval=False,
            latency_ms=0,
        )

    if permit_match:
        return EvaluationResult(
            decision="ALLOW",
            reason=f"Action '{action}' on '{resource}' is allowed by policy.",
            policy_id=permit_match["id"],
            requires_approval=False,
            latency_ms=0,
        )

    return EvaluationResult(
        decision="DENY",
        reason=f"No matching policy for '{action}' on '{resource}'. Denied by default.",
        policy_id=None,
        requires_approval=False,
        latency_ms=0,
    )


def _matches_rule(
    rule: str,
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object],
) -> bool:
    return _check_action_match(rule, action) and _check_when_clause(rule, resource, context)


def _check_action_match(rule: str, action: str) -> bool:
    all_actions_pattern = r"forbid\s*\(\s*principal\s*,\s*action\s*,"
    if re.search(all_actions_pattern, rule):
        action_specific = re.search(r"action\s*(==|in\s)", rule)
        if not action_specific:
            return True

    exact_pattern = rf'Action::"{re.escape(action)}"'
    return bool(re.search(exact_pattern, rule))


def _check_when_clause(
    rule: str,
    resource: str,
    context: dict[str, object],
) -> bool:
    when_match = re.search(r"when\s*\{([^}]+)\}", rule)
    if not when_match:
        return True

    conditions = when_match.group(1)

    resource_attrs = _extract_attr_pairs(conditions, "resource")
    for attr, expected in resource_attrs.items():
        actual = context.get(attr)
        if actual is None:
            return False
        if isinstance(expected, str) and expected.endswith("*"):
            if not str(actual).startswith(expected.rstrip("*")):
                return False
        elif str(actual) != str(expected):
            return False

    like_patterns = re.findall(r'resource\.(\w+)\s+like\s+"([^"]+)"', conditions)
    for attr, pattern in like_patterns:
        actual = context.get(attr, "")
        regex_pattern = pattern.replace("*", ".*").replace("?", ".")
        if not re.match(regex_pattern, str(actual)):
            return False

    context_attrs = _extract_attr_pairs(conditions, "context")
    for attr, expected in context_attrs.items():
        actual = context.get(attr)
        if actual is None:
            return False
        if str(actual) != str(expected):
            return False

    return True


def _extract_attr_pairs(conditions: str, prefix: str) -> dict[str, str]:
    """Extract `prefix.attr == "value"` pairs from a when-clause body."""
    result: dict[str, str] = {}
    pattern = rf'{prefix}\.(\w+)\s*==\s*"([^"]+)"'
    for match in re.finditer(pattern, conditions):
        result[match.group(1)] = match.group(2)
    return result
