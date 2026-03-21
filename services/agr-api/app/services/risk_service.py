"""Deterministic risk scoring engine.

Computes a 0-100 risk score for any evaluate request based on 5 weighted
factors. No LLM or external calls — purely rule-based, fast, and predictable.

Score interpretation:
  0-30   LOW    → safe to ALLOW
  31-70  MEDIUM → escalate to APPROVAL_REQUIRED
  71-100 HIGH   → DENY (too risky to proceed without policy override)

The thresholds are configurable via settings.risk_thresholds_*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class RiskResult:
    score: int  # 0-100
    level: str  # "low" | "medium" | "high"
    factors: dict[str, int]  # factor_name → partial score contribution


# ---------------------------------------------------------------------------
# Factor weights (must sum to 1.0)
# ---------------------------------------------------------------------------
_WEIGHTS = {
    "action_severity": 0.35,
    "context_signals": 0.25,
    "rate_pattern": 0.15,
    "agent_trust": 0.15,
    "amount_scale": 0.10,
}

# ---------------------------------------------------------------------------
# Keyword sets — order matters: first match wins
# ---------------------------------------------------------------------------

# Actions that are very destructive
_HIGH_SEVERITY_ACTIONS = re.compile(
    r"\b(drop|delete|destroy|terminate|nuke|truncate|purge|wipe|erase|"
    r"rm\b|remove|format|overwrite|exec|execute|shell|sudo|escalate)\b",
    re.IGNORECASE,
)

# Actions that are moderately risky
_MED_SEVERITY_ACTIONS = re.compile(
    r"\b(deploy|update|modify|patch|migrate|transfer|send|publish|"
    r"write|create|add|insert|post|put)\b",
    re.IGNORECASE,
)

# Context keys that signal elevated risk
_RISKY_CONTEXT_KEYS = frozenset(
    {
        "environment",
        "amount",
        "quantity",
        "count",
        "size",
        "bulk",
        "all",
        "recursive",
        "force",
        "override",
        "bypass",
        "admin",
        "root",
        "sudo",
    }
)

_HIGH_RISK_CONTEXT_VALUES = re.compile(
    r"\b(production|prod|live|critical|admin|root|all|bulk|recursive|force)\b",
    re.IGNORECASE,
)

# Agent prefixes that imply elevated trust
_TRUSTED_AGENT_PREFIXES = ("trusted-", "verified-", "approved-", "internal-")


# ---------------------------------------------------------------------------
# Individual factor scorers  (each returns 0-100)
# ---------------------------------------------------------------------------


def _score_action_severity(action: str) -> int:
    """Score 0-100 based on how destructive the action name is."""
    if _HIGH_SEVERITY_ACTIONS.search(action):
        return 90
    if _MED_SEVERITY_ACTIONS.search(action):
        return 45
    # Read-like actions
    if re.search(r"\b(read|get|list|view|fetch|query|search|show)\b", action, re.IGNORECASE):
        return 5
    return 20  # unknown action — slight caution


def _score_context_signals(context: dict[str, object]) -> int:
    """Score based on suspicious context keys and values."""
    if not context:
        return 0

    score = 0
    risky_key_count = sum(1 for k in context if k.lower() in _RISKY_CONTEXT_KEYS)
    score += min(risky_key_count * 10, 40)

    for v in context.values():
        if isinstance(v, str) and _HIGH_RISK_CONTEXT_VALUES.search(v):
            score += 20
            break  # one production hit is enough to flag

    return min(score, 100)


def _score_rate_pattern(eval_count: int, eval_limit: int) -> int:
    """Score based on how close the org is to its eval rate limit.

    High velocity near the limit indicates potential automated abuse.
    """
    if eval_limit <= 0:
        return 0  # unlimited plan — no rate pressure signal
    fraction = eval_count / eval_limit
    if fraction >= 0.9:
        return 70
    if fraction >= 0.7:
        return 40
    if fraction >= 0.5:
        return 20
    return 0


def _score_agent_trust(agent_id: str) -> int:
    """Score based on agent naming conventions.

    Trusted/verified agents lower risk; unknown IDs carry mild risk.
    """
    lower = agent_id.lower()
    if any(lower.startswith(pfx) for pfx in _TRUSTED_AGENT_PREFIXES):
        return 0
    # Generic agent IDs with numbers look automated
    if re.search(r"\d{4,}", agent_id):
        return 30
    return 15


def _score_amount_scale(context: dict[str, object]) -> int:
    """Score based on numeric magnitude signals in context (e.g. amount, count)."""
    for key in ("amount", "quantity", "count", "size", "limit"):
        val = context.get(key)
        if val is None:
            continue
        try:
            n = float(str(val))
        except (ValueError, TypeError):
            continue
        if n >= 1_000_000:
            return 90
        if n >= 10_000:
            return 60
        if n >= 1_000:
            return 35
        if n >= 100:
            return 15
    return 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_risk_score(
    agent_id: str,
    action: str,
    resource: str,
    context: dict[str, object],
    eval_count: int = 0,
    eval_limit: int = 0,
) -> RiskResult:
    """Compute the weighted risk score for an evaluate call.

    Args:
        agent_id:   The requesting agent identifier.
        action:     The action being requested.
        resource:   The target resource (informational only for now).
        context:    Arbitrary context key-value pairs.
        eval_count: Current org eval usage (for rate pattern scoring).
        eval_limit: Org eval limit (0 = unlimited).

    Returns:
        RiskResult with score (0-100), level ("low"|"medium"|"high"),
        and per-factor breakdown.
    """
    raw: dict[str, float] = {
        "action_severity": _score_action_severity(action),
        "context_signals": _score_context_signals(context),
        "rate_pattern": _score_rate_pattern(eval_count, eval_limit),
        "agent_trust": _score_agent_trust(agent_id),
        "amount_scale": _score_amount_scale(context),
    }

    weighted_score = sum(raw[k] * _WEIGHTS[k] for k in raw)
    final = min(100, max(0, round(weighted_score)))

    # Per-factor contribution (rounded integers for the response)
    factors = {k: round(raw[k] * _WEIGHTS[k]) for k in raw}

    if final <= 30:
        level = "low"
    elif final <= 70:
        level = "medium"
    else:
        level = "high"

    return RiskResult(score=final, level=level, factors=factors)
