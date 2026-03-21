"""AuditTrailCompliancePlugin — built-in plugin for audit trail requirements.

Checks that the evaluate call has the minimum data needed to satisfy:
  - EU AI Act Art. 13 (transparency + logging for high-risk AI)
  - SOC2 CC6.1 (logical access controls)
  - ISO 42001 §8.4 (AI system records)

All findings are advisory only. A "failed" finding does not block the request.
"""

from __future__ import annotations

import re

from app.services.compliance_service import (
    ComplianceContext,
    ComplianceFinding,
    CompliancePlugin,
)


class AuditTrailCompliancePlugin(CompliancePlugin):
    """Validates that each evaluate call meets minimum audit trail requirements."""

    @property
    def name(self) -> str:
        return "audit_trail_check"

    async def check(self, ctx: ComplianceContext) -> list[ComplianceFinding]:
        findings: list[ComplianceFinding] = []

        # EU AI Act Art. 13 — agent_id must be non-trivial (not empty/generic)
        _generic_ids = ("agent", "bot", "ai")
        agent_ok = bool(
            ctx.agent_id and len(ctx.agent_id) >= 3 and ctx.agent_id not in _generic_ids
        )
        findings.append(
            ComplianceFinding(
                plugin=self.name,
                standard="EU_AI_ACT",
                rule_id="ART-13",
                severity="warning",
                message=(
                    "Agent ID is sufficiently descriptive."
                    if agent_ok
                    else "Agent ID is missing or too generic. EU AI Act Art. 13 requires "
                    "identifiable AI actors in audit records."
                ),
                passed=agent_ok,
            )
        )

        # SOC2 CC6.1 — action must describe a specific operation (not empty/wildcard)
        action_ok = bool(
            ctx.action and ctx.action != "*" and not re.match(r"^[\*\?]+$", ctx.action)
        )
        findings.append(
            ComplianceFinding(
                plugin=self.name,
                standard="SOC2",
                rule_id="CC6.1",
                severity="warning",
                message=(
                    "Action is specific and auditable."
                    if action_ok
                    else "Action is a wildcard or empty — SOC2 CC6.1 requires "
                    "specific operation names in access control logs."
                ),
                passed=action_ok,
            )
        )

        # ISO 42001 §8.4 — resource must be identified
        resource_ok = bool(ctx.resource and ctx.resource != "*")
        findings.append(
            ComplianceFinding(
                plugin=self.name,
                standard="ISO42001",
                rule_id="SEC-8.4",
                severity="info",
                message=(
                    "Resource is identified in the request."
                    if resource_ok
                    else "Resource is missing or wildcard — ISO 42001 §8.4 recommends "
                    "specific resource identification in AI system records."
                ),
                passed=resource_ok,
            )
        )

        # EU AI Act Art. 13 — high-risk decisions should have context
        if ctx.decision in ("DENY", "APPROVAL_REQUIRED"):
            context_ok = bool(ctx.context)
            findings.append(
                ComplianceFinding(
                    plugin=self.name,
                    standard="EU_AI_ACT",
                    rule_id="ART-13-CONTEXT",
                    severity="info",
                    message=(
                        "Decision context provided for high-risk outcome."
                        if context_ok
                        else "No context provided for a DENY/APPROVAL_REQUIRED decision. "
                        "EU AI Act Art. 13 recommends contextual metadata for high-risk decisions."
                    ),
                    passed=context_ok,
                )
            )

        return findings
