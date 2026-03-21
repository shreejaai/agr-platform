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
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


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


@dataclass
class ComplianceFinding:
    """A single finding from a compliance plugin."""

    plugin: str  # plugin identifier (e.g. "audit_trail_check")
    standard: str  # e.g. "EU_AI_ACT", "SOC2", "ISO42001", "INTERNAL"
    rule_id: str  # e.g. "ART-13", "CC6.1"
    severity: str  # "info" | "warning" | "critical"
    message: str
    passed: bool  # True = compliant, False = violation found


@dataclass
class ComplianceResult:
    """Aggregated result from all plugins."""

    findings: list[ComplianceFinding] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return any(not f.passed for f in self.findings)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "critical" and not f.passed)

    def to_dict(self) -> list[dict[str, object]]:
        return [
            {
                "plugin": f.plugin,
                "standard": f.standard,
                "rule_id": f.rule_id,
                "severity": f.severity,
                "message": f.message,
                "passed": f.passed,
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
                logger.warning(
                    "Compliance plugin %s raised (skipping): %s", plugin.name, exc
                )

        return ComplianceResult(findings=all_findings)


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
