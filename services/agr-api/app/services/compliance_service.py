"""Compliance hook framework.

Provides an abstract plugin interface for regulatory/compliance checks
(EU AI Act, SOC2, ISO 42001, etc.). All plugins are:
  - Advisory only — they produce findings but never block requests
  - Fail-open — if a plugin raises, the error is logged and execution continues
  - Registered via ComplianceRegistry (populated at startup in main.py lifespan)

Usage:
    registry = get_registry()
    findings = await registry.run_all(context)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace

logger = logging.getLogger(__name__)

_VALID_SEVERITY_LEVELS = frozenset({"low", "medium", "high", "critical"})

_SEVERITY_BASE_POINTS = {"info": 20, "warning": 40, "critical": 75}
_SEVERITY_FLOOR_POINTS = {"low": 0, "medium": 40, "high": 65, "critical": 85}
_SCORE_BASE_PENALTIES = {"info": 20, "warning": 35, "critical": 55}
_RISK_LEVEL_POINTS = {"low": 0, "medium": 10, "high": 20, "critical": 30}


@dataclass(frozen=True)
class ComplianceRuleGuidance:
    severity_floor: str
    relevant_risk_factors: tuple[str, ...]
    remediation_steps: tuple[str, ...]


_DEFAULT_GUIDANCE = ComplianceRuleGuidance(
    severity_floor="low",
    relevant_risk_factors=(),
    remediation_steps=(
        "Update the caller so this control's required metadata is populated consistently.",
        "Review the matching policy or plugin rule and align the request payload with it.",
        "Re-run the evaluation and verify the finding passes before promoting the change.",
    ),
)

_RULE_GUIDANCE: dict[str, ComplianceRuleGuidance] = {
    "ART-13": ComplianceRuleGuidance(
        severity_floor="medium",
        relevant_risk_factors=("agent_trust", "context_signals"),
        remediation_steps=(
            "Use a stable, descriptive `agent_id` instead of a generic identifier.",
            "Register or update the agent metadata so audit records can identify the actor.",
            "Re-run the request and confirm the audit trail records the named agent.",
        ),
    ),
    "CC6.1": ComplianceRuleGuidance(
        severity_floor="medium",
        relevant_risk_factors=("action_severity", "rate_pattern"),
        remediation_steps=(
            "Replace wildcard or empty actions with the exact operation name being requested.",
            "Split broad actions into narrower, auditable operations where possible.",
            "Re-run the request and verify the action is logged with a specific verb.",
        ),
    ),
    "SEC-8.4": ComplianceRuleGuidance(
        severity_floor="low",
        relevant_risk_factors=("resource_sensitivity", "action_severity"),
        remediation_steps=(
            "Provide a concrete resource identifier instead of a wildcard or empty value.",
            "Include the target system, dataset, or record identifier in the request payload.",
            "Re-run the request and verify the resource is present in the audit record.",
        ),
    ),
    "ART-13-CONTEXT": ComplianceRuleGuidance(
        severity_floor="medium",
        relevant_risk_factors=("context_signals", "amount_scale", "resource_sensitivity"),
        remediation_steps=(
            "Attach decision context for denied or approval-gated requests.",
            "Include keys such as environment, justification, approval ticket, or scope details.",
            "Re-run the request and verify the audit event contains the same contextual metadata.",
        ),
    ),
}

_RISK_FACTOR_REMEDIATION: dict[str, str] = {
    "action_severity": (
        "Reduce the requested action scope or require a narrower operation before execution."
    ),
    "context_signals": (
        "Populate explicit environment, scope, and approval context so the request is auditable."
    ),
    "rate_pattern": (
        "Throttle repeated evaluations or review burst activity before retrying this workflow."
    ),
    "agent_trust": "Run the request from a trusted or verified registered agent identity.",
    "amount_scale": "Add tighter amount or count bounds and include them in the request context.",
    "resource_sensitivity": (
        "Target a less sensitive resource or ensure the sensitive target is named precisely."
    ),
}


@dataclass
class ComplianceContext:
    """Input to every compliance plugin."""

    org_id: str
    agent_id: str
    action: str
    resource: str
    context: dict[str, object]
    decision: str  # current decision after Cedar + risk scoring
    risk_score: int | None = None
    risk_level: str | None = None
    risk_factors: dict[str, int] | None = None


@dataclass
class ComplianceFinding:
    """A single finding from a compliance plugin."""

    plugin: str  # plugin identifier (e.g. "audit_trail_check")
    standard: str  # e.g. "EU_AI_ACT", "SOC2", "ISO42001", "INTERNAL"
    rule_id: str  # e.g. "ART-13", "CC6.1"
    severity: str  # "info" | "warning" | "critical"
    message: str
    passed: bool  # True = compliant, False = violation found
    remediation_steps: list[str] = field(default_factory=list)
    severity_level: str = "low"
    compliance_score: int = 100


@dataclass
class ComplianceResult:
    """Aggregated result from all plugins."""

    findings: list[ComplianceFinding] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return any(not f.passed for f in self.findings)

    @property
    def critical_count(self) -> int:
        return sum(
            1
            for f in self.findings
            if not f.passed and (f.severity_level == "critical" or f.severity == "critical")
        )

    @property
    def compliance_score(self) -> int:
        if not self.findings:
            return 100
        return round(sum(f.compliance_score for f in self.findings) / len(self.findings))

    def to_dict(self) -> list[dict[str, object]]:
        return [
            {
                "plugin": f.plugin,
                "standard": f.standard,
                "rule_id": f.rule_id,
                "severity": f.severity,
                "message": f.message,
                "passed": f.passed,
                "remediation_steps": f.remediation_steps,
                "severity_level": f.severity_level,
                "compliance_score": f.compliance_score,
            }
            for f in self.findings
        ]


class CompliancePlugin(ABC):
    """Abstract base class for all compliance plugins.

    Implement `check()` to return a list of findings for a given context.
    Raising from `check()` is safe — the registry catches and logs it.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this plugin."""

    @abstractmethod
    async def check(self, ctx: ComplianceContext) -> list[ComplianceFinding]:
        """Run compliance checks and return findings.

        Must not raise — return findings with passed=False for violations.
        If raising is unavoidable, the registry will catch and log it.
        """


class ComplianceRegistry:
    """Registry of compliance plugins. Thread-safe for reads after startup."""

    def __init__(self) -> None:
        self._plugins: list[CompliancePlugin] = []

    def register(self, plugin: CompliancePlugin) -> None:
        """Register a plugin. Called at application startup."""
        self._plugins.append(plugin)
        logger.info("Registered compliance plugin: %s", plugin.name)

    @property
    def plugins(self) -> list[CompliancePlugin]:
        return list(self._plugins)

    async def run_all(self, ctx: ComplianceContext) -> ComplianceResult:
        """Run all registered plugins and aggregate findings.

        Fail-open: plugin errors are logged and skipped — never crash the request.
        """
        all_findings: list[ComplianceFinding] = []

        for plugin in self._plugins:
            try:
                findings = await plugin.check(ctx)
                all_findings.extend(findings)
            except Exception as exc:
                # M9: re-raise process-terminating signals — never swallow them
                if isinstance(exc, SystemExit | KeyboardInterrupt):
                    raise
                logger.warning("Compliance plugin %s raised (skipping): %s", plugin.name, exc)

        return ComplianceResult(
            findings=[
                enrich_compliance_finding(
                    finding,
                    risk_score=ctx.risk_score,
                    risk_level=ctx.risk_level,
                    risk_factors=ctx.risk_factors,
                )
                for finding in all_findings
            ]
        )


# Module-level singleton — populated by main.py lifespan
_registry: ComplianceRegistry | None = None


def get_registry() -> ComplianceRegistry:
    """Return the module-level compliance registry, creating it if needed."""
    global _registry
    if _registry is None:
        _registry = ComplianceRegistry()
    return _registry


def reset_registry() -> None:
    """Reset the registry. Used in tests only."""
    global _registry
    _registry = None


def _normalize_risk_level(risk_level: str | None, risk_score: int | None) -> str:
    normalized = (risk_level or "").lower()
    if normalized in _VALID_SEVERITY_LEVELS:
        return normalized
    if risk_score is None:
        return "low"
    if risk_score >= 90:
        return "critical"
    if risk_score > 70:
        return "high"
    if risk_score > 30:
        return "medium"
    return "low"


def _level_from_points(points: int) -> str:
    if points >= _SEVERITY_FLOOR_POINTS["critical"]:
        return "critical"
    if points >= _SEVERITY_FLOOR_POINTS["high"]:
        return "high"
    if points >= _SEVERITY_FLOOR_POINTS["medium"]:
        return "medium"
    return "low"


def _relevant_risk_pressure(
    risk_factors: dict[str, int] | None, relevant_risk_factors: tuple[str, ...]
) -> int:
    if not risk_factors or not relevant_risk_factors:
        return 0
    return min(sum(max(0, risk_factors.get(name, 0)) for name in relevant_risk_factors), 40)


def _dedupe_steps(steps: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for step in steps:
        if step in seen:
            continue
        seen.add(step)
        ordered.append(step)
    return ordered


def _build_remediation_steps(
    finding: ComplianceFinding,
    guidance: ComplianceRuleGuidance,
    risk_factors: dict[str, int] | None,
) -> list[str]:
    if finding.passed:
        return []

    steps = list(guidance.remediation_steps)
    if risk_factors:
        for factor_name in guidance.relevant_risk_factors:
            contribution = risk_factors.get(factor_name, 0)
            if contribution < 8:
                continue
            risk_step = _RISK_FACTOR_REMEDIATION.get(factor_name)
            if risk_step is not None:
                steps.append(risk_step)

    steps.append(
        "Confirm the finding clears in the simulator or /v1/evaluate response after the fix."
    )
    return _dedupe_steps(steps)


def enrich_compliance_finding(
    finding: ComplianceFinding,
    *,
    risk_score: int | None = None,
    risk_level: str | None = None,
    risk_factors: dict[str, int] | None = None,
) -> ComplianceFinding:
    if finding.passed:
        return replace(
            finding,
            remediation_steps=[],
            severity_level="low",
            compliance_score=100,
        )

    guidance = _RULE_GUIDANCE.get(finding.rule_id, _DEFAULT_GUIDANCE)
    normalized_risk_level = _normalize_risk_level(risk_level, risk_score)
    risk_pressure = _relevant_risk_pressure(risk_factors, guidance.relevant_risk_factors)

    severity_points = max(
        _SEVERITY_BASE_POINTS.get(finding.severity, _SEVERITY_BASE_POINTS["info"])
        + _RISK_LEVEL_POINTS[normalized_risk_level]
        + round(risk_pressure * 0.75),
        _SEVERITY_FLOOR_POINTS[guidance.severity_floor],
    )
    compliance_score = max(
        0,
        100
        - _SCORE_BASE_PENALTIES.get(finding.severity, _SCORE_BASE_PENALTIES["info"])
        - _RISK_LEVEL_POINTS[normalized_risk_level]
        - round(risk_pressure * 0.6),
    )

    return replace(
        finding,
        remediation_steps=_build_remediation_steps(finding, guidance, risk_factors),
        severity_level=_level_from_points(severity_points),
        compliance_score=compliance_score,
    )


def normalize_compliance_finding_payload(
    raw_finding: dict[str, object],
    *,
    risk_score: int | None = None,
    risk_level: str | None = None,
    risk_factors: dict[str, int] | None = None,
) -> dict[str, object]:
    remediation_steps = raw_finding.get("remediation_steps")
    severity_level = raw_finding.get("severity_level")
    compliance_score = raw_finding.get("compliance_score")
    if (
        isinstance(remediation_steps, list)
        and all(isinstance(step, str) for step in remediation_steps)
        and isinstance(severity_level, str)
        and severity_level in _VALID_SEVERITY_LEVELS
        and isinstance(compliance_score, int)
        and 0 <= compliance_score <= 100
    ):
        return {
            "plugin": str(raw_finding.get("plugin", "")),
            "standard": str(raw_finding.get("standard", "UNKNOWN")),
            "rule_id": str(raw_finding.get("rule_id", "UNKNOWN")),
            "severity": str(raw_finding.get("severity", "info")),
            "message": str(raw_finding.get("message", "")),
            "passed": bool(raw_finding.get("passed")),
            "remediation_steps": remediation_steps,
            "severity_level": severity_level,
            "compliance_score": compliance_score,
        }

    finding = ComplianceFinding(
        plugin=str(raw_finding.get("plugin", "")),
        standard=str(raw_finding.get("standard", "UNKNOWN")),
        rule_id=str(raw_finding.get("rule_id", "UNKNOWN")),
        severity=str(raw_finding.get("severity", "info")),
        message=str(raw_finding.get("message", "")),
        passed=bool(raw_finding.get("passed")),
    )
    return enrich_compliance_finding(
        finding,
        risk_score=risk_score,
        risk_level=risk_level,
        risk_factors=risk_factors,
    ).__dict__
