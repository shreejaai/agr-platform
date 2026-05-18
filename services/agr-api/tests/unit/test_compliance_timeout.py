"""W3.4 — Compliance plugin per-plugin timeout.

A plugin that exceeds the configured budget must:
  - be cancelled (not block the request)
  - surface as an advisory warning finding (passed=False, severity="warning")
  - not raise out of run_all
"""

from __future__ import annotations

import asyncio

import pytest
from app.config import settings
from app.services.compliance_service import (
    ComplianceContext,
    ComplianceFinding,
    CompliancePlugin,
    ComplianceRegistry,
)


class _SlowPlugin(CompliancePlugin):
    name = "slow_test_plugin"
    standard = "INTERNAL"

    async def check(self, ctx: ComplianceContext) -> list[ComplianceFinding]:
        await asyncio.sleep(0.2)  # 200ms — well beyond 10ms test budget
        return [
            ComplianceFinding(
                plugin=self.name,
                standard="INTERNAL",
                rule_id="NEVER",
                severity="info",
                message="should not be returned",
                passed=True,
            )
        ]


@pytest.mark.asyncio
async def test_slow_plugin_emits_timeout_advisory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "compliance_plugin_timeout_ms", 10)
    registry = ComplianceRegistry()
    registry.register(_SlowPlugin())

    ctx = ComplianceContext(
        org_id="00000000-0000-0000-0000-000000000001",
        agent_id="agent-1",
        action="x",
        resource="y",
        context={},
        decision="ALLOW",
    )

    result = await registry.run_all(ctx)

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.rule_id == "PLUGIN-TIMEOUT"
    assert finding.severity == "warning"
    assert finding.passed is False
    assert finding.plugin == "slow_test_plugin"
    assert result.blocked is False
