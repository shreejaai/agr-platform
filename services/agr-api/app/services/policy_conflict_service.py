"""Policy conflict detection — advisory, non-blocking.

Detects two classes of conflict between a candidate rule and existing
active/draft policies for an org:

1. Exact duplicate  — identical cedar_rule (ignoring whitespace)
2. Action conflict  — a permit and a forbid rule targeting the same action
                      (forbid always wins in Cedar, so the permit is silenced)

Results are returned as human-readable warning strings.  The caller decides
whether to surface them to the API consumer; they never block write operations.
"""

from __future__ import annotations

import re


def _normalise(rule: str) -> str:
    """Strip leading/trailing whitespace and collapse internal runs."""
    return re.sub(r"\s+", " ", rule.strip())


def _extract_action(rule: str) -> str | None:
    """Return the action literal from a Cedar rule, or None if not found."""
    m = re.search(r'Action::"([^"]+)"', rule)
    return m.group(1) if m else None


def _is_permit(rule: str) -> bool:
    return _normalise(rule).lower().startswith("permit")


def _is_forbid(rule: str) -> bool:
    return _normalise(rule).lower().startswith("forbid")


def detect_conflicts(
    candidate_rule: str,
    candidate_name: str,
    existing_policies: list[dict[str, str]],
) -> list[str]:
    """Return advisory warning strings for conflicts between candidate and existing policies.

    Args:
        candidate_rule:   The cedar_rule being created or updated.
        candidate_name:   The policy name (used in messages).
        existing_policies: List of dicts with keys 'id', 'name', 'cedar_rule'.
                           Should include only active/draft policies (not archived).

    Returns:
        List of human-readable warning strings.  Empty list = no conflicts.
    """
    warnings: list[str] = []
    norm_candidate = _normalise(candidate_rule)
    candidate_action = _extract_action(candidate_rule)
    candidate_is_permit = _is_permit(candidate_rule)
    candidate_is_forbid = _is_forbid(candidate_rule)

    for existing in existing_policies:
        existing_rule = existing.get("cedar_rule", "")
        existing_name = existing.get("name", existing.get("id", "unknown"))

        # 1. Exact duplicate
        if _normalise(existing_rule) == norm_candidate:
            warnings.append(
                f"Duplicate: '{candidate_name}' has the same rule as existing policy "
                f"'{existing_name}'."
            )
            continue

        # 2. Action conflict (permit ↔ forbid on same action)
        if candidate_action is None:
            continue
        existing_action = _extract_action(existing_rule)
        if existing_action != candidate_action:
            continue

        existing_is_permit = _is_permit(existing_rule)
        existing_is_forbid = _is_forbid(existing_rule)

        if candidate_is_permit and existing_is_forbid:
            warnings.append(
                f"Conflict: '{candidate_name}' permits action '{candidate_action}' but "
                f"existing policy '{existing_name}' forbids it — the forbid will win."
            )
        elif candidate_is_forbid and existing_is_permit:
            warnings.append(
                f"Conflict: '{candidate_name}' forbids action '{candidate_action}' but "
                f"existing policy '{existing_name}' permits it — this forbid will win."
            )

    return warnings
