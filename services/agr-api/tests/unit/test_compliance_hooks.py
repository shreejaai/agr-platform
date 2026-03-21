"""Unit tests for the compliance hooks framework."""

import pytest
from app.services.compliance_plugins.audit_trail_check import AuditTrailCompliancePlugin
from app.services.compliance_service import (
    ComplianceContext,
    ComplianceFinding,
    CompliancePlugin,
    ComplianceRegistry,
    ComplianceResult,
    get_registry,
    reset_registry,
)


def _ctx(**kwargs) -> ComplianceContext:
    defaults = dict(
        org_id="org-1",
        agent_id="agent-test",
        action="read",
        resource="file.txt",
        context={},
        decision="ALLOW",
    )
    defaults.update(kwargs)
    return ComplianceContext(**defaults)


# ---------------------------------------------------------------------------
# Framework tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_runs_all_plugins() -> None:
    registry = ComplianceRegistry()

    class AlwaysPassPlugin(CompliancePlugin):
        @property
        def name(self) -> str:
            return "always_pass"

        async def check(self, ctx: ComplianceContext) -> list[ComplianceFinding]:
            return [
                ComplianceFinding(
                    plugin=self.name,
                    standard="INTERNAL",
                    rule_id="T1",
                    severity="info",
                    message="ok",
                    passed=True,
                )
            ]

    registry.register(AlwaysPassPlugin())
    result = await registry.run_all(_ctx())
    assert len(result.findings) == 1
    assert result.findings[0].passed is True
    assert not result.has_violations


@pytest.mark.asyncio
async def test_registry_fail_open_on_plugin_error() -> None:
    """A crashing plugin does not propagate — other plugins still run."""
    registry = ComplianceRegistry()

    class BrokenPlugin(CompliancePlugin):
        @property
        def name(self) -> str:
            return "broken"

        async def check(self, ctx: ComplianceContext) -> list[ComplianceFinding]:
            raise RuntimeError("simulated plugin failure")

    class GoodPlugin(CompliancePlugin):
        @property
        def name(self) -> str:
            return "good"

        async def check(self, ctx: ComplianceContext) -> list[ComplianceFinding]:
            return [
                ComplianceFinding(
                    plugin=self.name,
                    standard="INTERNAL",
                    rule_id="G1",
                    severity="info",
                    message="ok",
                    passed=True,
                )
            ]

    registry.register(BrokenPlugin())
    registry.register(GoodPlugin())

    result = await registry.run_all(_ctx())
    # GoodPlugin should still run even after BrokenPlugin crashes
    assert len(result.findings) == 1
    assert result.findings[0].plugin == "good"


@pytest.mark.asyncio
async def test_compliance_result_has_violations() -> None:
    result = ComplianceResult(
        findings=[
            ComplianceFinding(
                plugin="p",
                standard="S",
                rule_id="R1",
                severity="warning",
                message="fail",
                passed=False,
            )
        ]
    )
    assert result.has_violations is True


@pytest.mark.asyncio
async def test_compliance_result_to_dict() -> None:
    result = ComplianceResult(
        findings=[
            ComplianceFinding(
                plugin="audit_trail",
                standard="SOC2",
                rule_id="CC6.1",
                severity="info",
                message="ok",
                passed=True,
            )
        ]
    )
    dicts = result.to_dict()
    assert len(dicts) == 1
    assert dicts[0]["plugin"] == "audit_trail"
    assert dicts[0]["passed"] is True


# ---------------------------------------------------------------------------
# AuditTrailCompliancePlugin tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_trail_passes_valid_request() -> None:
    plugin = AuditTrailCompliancePlugin()
    ctx = _ctx(agent_id="my-agent-01", action="deploy", resource="server-1")
    findings = await plugin.check(ctx)
    assert all(f.passed for f in findings if f.rule_id in ("ART-13", "CC6.1", "SEC-8.4"))


@pytest.mark.asyncio
async def test_audit_trail_fails_generic_agent_id() -> None:
    plugin = AuditTrailCompliancePlugin()
    ctx = _ctx(agent_id="bot")
    findings = await plugin.check(ctx)
    art13 = next(f for f in findings if f.rule_id == "ART-13")
    assert art13.passed is False


@pytest.mark.asyncio
async def test_audit_trail_fails_wildcard_action() -> None:
    plugin = AuditTrailCompliancePlugin()
    ctx = _ctx(action="*")
    findings = await plugin.check(ctx)
    cc61 = next(f for f in findings if f.rule_id == "CC6.1")
    assert cc61.passed is False


@pytest.mark.asyncio
async def test_audit_trail_context_check_on_deny() -> None:
    plugin = AuditTrailCompliancePlugin()
    ctx = _ctx(decision="DENY", context={})
    findings = await plugin.check(ctx)
    context_finding = next((f for f in findings if f.rule_id == "ART-13-CONTEXT"), None)
    assert context_finding is not None
    assert context_finding.passed is False


@pytest.mark.asyncio
async def test_audit_trail_no_context_check_on_allow() -> None:
    """ART-13-CONTEXT check only triggers for DENY/APPROVAL_REQUIRED."""
    plugin = AuditTrailCompliancePlugin()
    ctx = _ctx(decision="ALLOW", context={})
    findings = await plugin.check(ctx)
    context_finding = next((f for f in findings if f.rule_id == "ART-13-CONTEXT"), None)
    assert context_finding is None


@pytest.mark.asyncio
async def test_get_registry_singleton() -> None:
    reset_registry()
    r1 = get_registry()
    r2 = get_registry()
    assert r1 is r2
    reset_registry()
