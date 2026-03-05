"""Cedar policy evaluation engine.

Primary: calls cedar-policy CLI via subprocess.
Fallback: simple Python evaluator for local dev without cedar CLI installed.
"""

import logging
import re
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    decision: str  # "ALLOW" | "DENY"
    reason: str
    policy_id: str | None
    requires_approval: bool
    latency_ms: float


def evaluate_policies(
    cedar_policies: list[dict[str, str]],
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object],
) -> EvaluationResult:
    """Evaluate Cedar policies using the Python fallback evaluator.

    Each policy dict must have keys: id, cedar_rule.
    Returns EvaluationResult with the decision.
    """
    start = time.perf_counter_ns()

    if not cedar_policies:
        elapsed = (time.perf_counter_ns() - start) / 1_000_000
        return EvaluationResult(
            decision="DENY",
            reason="No active policies found. All actions are denied by default.",
            policy_id=None,
            requires_approval=False,
            latency_ms=elapsed,
        )

    result = _python_evaluator(cedar_policies, agent_id, action, resource, context)
    elapsed = (time.perf_counter_ns() - start) / 1_000_000
    result.latency_ms = elapsed
    return result


def _python_evaluator(
    policies: list[dict[str, str]],
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object],
) -> EvaluationResult:
    """Simple Python-based Cedar policy evaluator for local dev.

    Parses Cedar forbid/permit rules and evaluates them against the request.
    Forbid rules take precedence over permit rules (deny-overrides).
    """
    forbid_match: dict[str, str] | None = None
    permit_match: dict[str, str] | None = None
    approval_required = False

    for policy in policies:
        rule = policy["cedar_rule"]

        lines = rule.strip().split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("//"):
                continue

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
    """Check if a Cedar rule matches the given request.

    Supports basic Cedar patterns:
    - action == Action::"name"
    - action in [Action::"a", Action::"b"]
    - resource has field && resource.field == "value"
    - resource.path like "pattern"
    - context has field && context.field == "value"
    """
    action_match = _check_action_match(rule, action)
    if not action_match:
        return False

    when_match = _check_when_clause(rule, resource, context)
    return when_match


def _check_action_match(rule: str, action: str) -> bool:
    """Check if the action matches the rule's action constraint."""
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
    """Check if when clause conditions are met."""
    when_match = re.search(r"when\s*\{([^}]+)\}", rule)
    if not when_match:
        return True

    conditions = when_match.group(1)

    resource_attrs = _extract_resource_context(conditions, "resource")
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

    context_attrs = _extract_resource_context(conditions, "context")
    for attr, expected in context_attrs.items():
        actual = context.get(attr)
        if actual is None:
            return False
        if str(actual) != str(expected):
            return False

    return True


def _extract_resource_context(conditions: str, prefix: str) -> dict[str, str]:
    """Extract field == value pairs from conditions for a given prefix."""
    result: dict[str, str] = {}
    pattern = rf'{prefix}\.(\w+)\s*==\s*"([^"]+)"'
    for match in re.finditer(pattern, conditions):
        result[match.group(1)] = match.group(2)
    return result
