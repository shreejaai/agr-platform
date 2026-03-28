import re
import urllib.parse
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# L5: strip null bytes and ASCII control characters from free-text fields.
# Null bytes crash some logging systems; control chars can confuse log parsers
# and policy evaluators. Non-breaking — valid agent IDs are never control chars.
_CTRL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _strip_ctrl(v: str) -> str:
    return _CTRL_CHARS.sub("", v)


EngineMode = Literal["cedar_cli", "python_fallback", "cache"]
ComplianceEnforcementMode = Literal["advisory", "enforce"]


class EvaluateRequest(BaseModel):
    agent_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Unique identifier for the agent making the request.",
        examples=["langgraph-prod-agent-1"],
    )
    action: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Action the agent wants to perform (maps to Cedar Action entity).",
        examples=["deploy", "read_secret", "send_email"],
    )
    resource: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="Resource identifier the action targets.",
        examples=["prod-database", "customer-pii-bucket"],
    )
    # M6: limit context to 50 keys to prevent DoS via huge payloads
    context: dict[str, object] = Field(
        default_factory=dict,
        description="Arbitrary context key/values evaluated in Cedar when clauses. Max 50 keys.",
        examples=[{"env": "production", "region": "us-east-1"}],
    )
    approver_email: str | None = Field(
        default=None,
        max_length=256,
        description="Override approver email for this specific request.",
    )

    @field_validator("agent_id", "action", "resource")
    @classmethod
    def strip_control_chars(cls, v: str) -> str:
        return _strip_ctrl(v)

    @field_validator("context")
    @classmethod
    def context_size_limit(cls, v: dict[str, object]) -> dict[str, object]:
        if len(v) > 50:
            raise ValueError("context must have at most 50 keys.")
        return v


class DecisionTrace(BaseModel):
    policy_source: str = Field(
        ...,
        description=(
            "Policy engine that produced the decision. "
            "'cedar_cli' = authoritative Cedar binary; "
            "'python_fallback' = regex approximation (dev/degraded mode); "
            "'no_policies' = no active policies found; "
            "'cache' = served from Redis cache."
        ),
    )
    matched_policy_id: str | None = None
    cedar_decision: str = Field(
        ...,
        description="Raw policy engine decision before risk scoring could override it.",
    )
    risk_score: int | None = None
    risk_level: str | None = None
    risk_override: bool = Field(
        default=False,
        description="True when risk scoring upgraded the Cedar ALLOW to APPROVAL_REQUIRED or DENY.",
    )
    fallback_used: bool = Field(
        default=False,
        description=(
            "True when the Python regex fallback was used instead of Cedar CLI. "
            "Fallback results may differ from Cedar in edge cases — "
            "install cedar-policy-cli for authoritative enforcement."
        ),
    )
    fallback_reason: str | None = Field(
        default=None,
        description="Machine-readable reason Cedar CLI was not used (populated when fallback_used=true).",
    )


class ComplianceFindingResponse(BaseModel):
    plugin: str
    standard: str
    rule_id: str
    severity: str
    message: str
    passed: bool
    remediation_steps: list[str] = Field(
        default_factory=list,
        description="Deterministic remediation guidance derived from the violated control and risk signals.",
    )
    severity_level: Literal["low", "medium", "high", "critical"] = Field(
        ...,
        description="Normalized severity level derived from the finding and request risk factors.",
    )
    compliance_score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Deterministic compliance score for this finding. Higher is better.",
    )


class EvaluateResponse(BaseModel):
    decision: str = Field(..., description="ALLOW | DENY | APPROVAL_REQUIRED", examples=["ALLOW"])
    reason: str = Field(..., description="Human-readable explanation of the decision.")
    policy_id: str | None = Field(default=None, description="UUID of the matching Cedar policy.")
    approval_id: str | None = Field(
        default=None, description="UUID of the created approval (APPROVAL_REQUIRED only)."
    )
    latency_ms: float = Field(..., description="End-to-end evaluation latency in milliseconds.")
    eval_id: str = Field(..., description="Unique evaluation identifier for audit lookup.")
    engine_mode: EngineMode = Field(
        default="cedar_cli",
        description="Execution engine used for this response.",
    )
    risk_score: int | None = Field(
        default=None, description="0-100 risk score. Higher = more risk.", ge=0, le=100
    )
    risk_level: str | None = Field(default=None, description="low | medium | high | critical")
    risk_factors: dict[str, int] | None = Field(
        default=None,
        description="Per-factor risk contributions. Keys: action_severity, data_sensitivity, agent_trust, context_risk, time_risk.",
    )
    compliance_findings: list[ComplianceFindingResponse] | None = Field(
        default=None, description="Advisory compliance findings (EU AI Act, SOC2, ISO42001)."
    )
    compliance_block: bool = Field(
        default=False,
        description="True when a compliance plugin in enforce mode blocked the request.",
    )
    compliance_reason: str | None = Field(
        default=None,
        description="Structured denial reason from the blocking compliance finding, when present.",
    )
    compliance_blocked: bool = Field(
        default=False,
        description="True when a compliance control upgraded the result to DENY.",
    )
    idempotency_replayed: bool = Field(
        default=False,
        description="True when the response was replayed from a previous Idempotency-Key result.",
    )
    anomaly_detected: bool = Field(
        default=False,
        description="True when AGR detected unusual behavior for this agent/action pair.",
    )
    anomaly_flags: list[str] = Field(
        default_factory=list,
        description="Machine-readable anomaly labels such as 'new_action'.",
    )
    decision_trace: DecisionTrace | None = Field(
        default=None, description="Internal decision trace for debugging."
    )


def _validate_cedar_rule(rule: str) -> str:
    """L6: Basic Cedar policy structure validation.

    Full semantic validation requires the Cedar CLI (not yet wired in).
    These checks catch the most common authoring mistakes before they
    reach the policy evaluator and produce confusing 'permit everything'
    or 'deny everything' behaviour.
    """
    stripped = rule.strip()
    if not stripped:
        raise ValueError("Cedar rule cannot be empty.")
    lower = stripped.lower()
    if not (lower.startswith("permit") or lower.startswith("forbid")):
        raise ValueError("Cedar rule must start with 'permit' or 'forbid'.")
    if not stripped.rstrip().endswith(";"):
        raise ValueError("Cedar rule must end with ';'.")
    # Balanced parentheses
    depth = 0
    for ch in stripped:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if depth < 0:
            raise ValueError("Cedar rule has unmatched closing parenthesis.")
    if depth != 0:
        raise ValueError("Cedar rule has unclosed parenthesis.")
    return rule


class PolicyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    level: str = Field(..., pattern=r"^(org|project|agent)$")
    cedar_rule: str = Field(..., min_length=1)
    project_id: uuid.UUID | None = None
    agent_id: str | None = None
    # New policies start as drafts — call /activate to put them into evaluation
    state: str = Field(default="draft", pattern=r"^(draft|active)$")

    @field_validator("cedar_rule")
    @classmethod
    def validate_cedar(cls, v: str) -> str:
        return _validate_cedar_rule(v)


class PolicyUpdate(BaseModel):
    cedar_rule: str | None = None
    # active is kept for backward compat; prefer the /activate and /archive endpoints
    active: bool | None = None
    name: str | None = None

    @field_validator("cedar_rule")
    @classmethod
    def validate_cedar(cls, v: str | None) -> str | None:
        if v is not None:
            _validate_cedar_rule(v)
        return v


class PolicyResponse(BaseModel):
    id: str
    org_id: str
    project_id: str | None
    agent_id: str | None
    name: str
    level: str
    cedar_rule: str
    version: int
    active: bool
    state: str
    created_at: datetime
    updated_at: datetime
    # Advisory conflict warnings — populated on create/update, None on list/get
    conflicts: list[str] | None = None


class ApprovalStepResponse(BaseModel):
    id: str
    approval_id: str
    approver_email: str
    status: str
    decided_at: datetime | None
    created_at: datetime


class ApprovalStepCreate(BaseModel):
    approver_email: str = Field(..., min_length=1, max_length=256)


class ApprovalResponse(BaseModel):
    id: str
    org_id: str
    agent_id: str
    action: str
    resource: str
    context: dict[str, object] | None
    status: str
    approver_email: str | None
    decision_at: datetime | None
    expires_at: datetime
    quorum_type: str = "any"
    sla_hours: int | None = None
    escalation_email: str | None = None
    created_at: datetime
    # Temporal observability — indicates whether a durable workflow is tracking this approval.
    # "temporal"  — Temporal workflow is active (durable, survives restarts)
    # "db_only"   — Temporal not configured; approval tracked by DB row only
    workflow_mode: Literal["temporal", "db_only"] = Field(
        default="db_only",
        description=(
            "Workflow tracking mode: 'temporal' when a durable Temporal workflow "
            "was started; 'db_only' when Temporal is not configured."
        ),
    )
    temporal_run_id: str | None = Field(
        default=None,
        description="Temporal workflow ID (present when workflow_mode='temporal').",
    )
    workflow_status: Literal["running", "completed", "failed", "escalated"] = Field(
        default="running",
        description="Current durable workflow state for the approval lifecycle.",
    )
    workflow_last_error: str | None = Field(
        default=None,
        description="Most recent workflow execution or signaling error, when present.",
    )
    workflow_last_transition_at: datetime | None = Field(
        default=None,
        description="Timestamp of the last workflow status transition.",
    )
    workflow_fallback_mode: str = Field(
        default="none",
        description=(
            "Explicit fallback state. 'none' means normal Temporal tracking or no fallback "
            "was needed; other values explain why the approval is operating in a degraded mode."
        ),
    )
    workflow_escalated_at: datetime | None = Field(
        default=None,
        description="Timestamp of the latest escalation event, if the workflow was escalated.",
    )


class ApprovalDecisionRequest(BaseModel):
    decided_by: str = Field(default="api_user", max_length=256)
    reason: str = Field(default="", max_length=1024)


class ApprovalDecideRequest(BaseModel):
    decision: str = Field(..., pattern=r"^(approved|rejected)$")
    decided_by: str = Field(default="api_user", max_length=256)
    reason: str = Field(default="", max_length=1024)


class AuditEventResponse(BaseModel):
    id: str
    org_id: str
    sequence_num: int
    event_type: str
    agent_id: str
    action: str
    resource: str
    decision: str
    policy_id: str | None
    approval_id: str | None
    payload: dict[str, object] | None
    prev_hash: str | None
    entry_hash: str
    recorded_at: datetime


class AgentRegisterRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=256)
    metadata: dict[str, object] = Field(default_factory=dict)
    name: str | None = Field(default=None, max_length=256)
    owner: str | None = Field(default=None, max_length=256)
    framework: str | None = Field(default=None, max_length=64)
    environment: str | None = Field(default=None, max_length=64)
    trust_level: str = Field(default="unknown", pattern=r"^(trusted|verified|unknown|untrusted)$")
    capabilities: list[str] = Field(default_factory=list)


class AgentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=1024)
    framework: str | None = Field(default=None, max_length=64)
    owner: str | None = Field(default=None, max_length=256)
    environment: str | None = Field(default=None, max_length=64)
    trust_level: str | None = Field(default=None, pattern=r"^(trusted|verified|unknown|untrusted)$")
    capabilities: list[str] | None = None
    active: bool | None = None


class AgentResponse(BaseModel):
    id: str
    org_id: str
    agent_id: str
    metadata: dict[str, object] | None
    name: str | None
    owner: str | None
    framework: str | None
    environment: str | None
    trust_level: str
    capabilities: list[str]
    active: bool
    created_at: datetime
    updated_at: datetime


class ActionStats(BaseModel):
    action: str
    count: int = Field(..., ge=0)


class AgentBehaviorResponse(BaseModel):
    agent_id: str
    action_baseline: list[ActionStats] = Field(default_factory=list)
    anomalies_detected: list[str] = Field(default_factory=list)


class OrgRiskConfigResponse(BaseModel):
    org_id: str
    weight_action_severity: float
    weight_context_signals: float
    weight_rate_pattern: float
    weight_agent_trust: float
    weight_amount_scale: float
    weight_resource_sensitivity: float
    threshold_allow_max: int
    threshold_approval_max: int
    updated_at: datetime


class OrgRiskConfigUpdate(BaseModel):
    weight_action_severity: float | None = Field(default=None, ge=0.0, le=1.0)
    weight_context_signals: float | None = Field(default=None, ge=0.0, le=1.0)
    weight_rate_pattern: float | None = Field(default=None, ge=0.0, le=1.0)
    weight_agent_trust: float | None = Field(default=None, ge=0.0, le=1.0)
    weight_amount_scale: float | None = Field(default=None, ge=0.0, le=1.0)
    weight_resource_sensitivity: float | None = Field(default=None, ge=0.0, le=1.0)
    threshold_allow_max: int | None = Field(default=None, ge=0, le=100)
    threshold_approval_max: int | None = Field(default=None, ge=0, le=100)


class ApprovalEscalateRequest(BaseModel):
    approver_email: str = Field(..., min_length=1, max_length=256)


class AuditVerifyResponse(BaseModel):
    valid: bool
    total: int
    first_invalid_sequence: int | None = None


class AuditSearchRequest(BaseModel):
    """POST body for /v1/audit/search — structured filter query."""

    event_type: str | None = None
    agent_id: str | None = None
    action: str | None = None
    resource: str | None = None
    decision: str | None = None
    policy_id: uuid.UUID | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class AuditExportJobResponse(BaseModel):
    job_id: str
    status: Literal["pending", "ready", "failed"]
    format: Literal["json", "csv"]
    download_url: str | None = None
    error: str | None = None


class ComplianceSummaryResponse(BaseModel):
    period_days: int
    total_evaluations: int
    decisions: dict[str, int]  # ALLOW/DENY/APPROVAL_REQUIRED counts
    high_risk_count: int
    findings_by_standard: dict[str, dict[str, int]]  # standard → {pass, fail}
    overall_pass: bool
    compliance_score: int = Field(
        ..., ge=0, le=100, description="Aggregate compliance score across sampled findings."
    )


class ComplianceConfigResponse(BaseModel):
    plugin_id: str
    enforcement_mode: ComplianceEnforcementMode


class ComplianceConfigUpdate(BaseModel):
    plugin_id: str = Field(..., min_length=1, max_length=64)
    enforcement_mode: ComplianceEnforcementMode


class OrgMeResponse(BaseModel):
    id: str
    name: str
    slug: str | None
    plan: str
    eval_count: int
    eval_limit: int
    eval_warning_threshold_pct: int = 80
    eval_soft_limit_enabled: bool = True
    eval_week_start: datetime | None = None
    role: str = "admin"
    auth_mode: Literal["api_key", "sso_session"] = "api_key"
    auth_expires_at: datetime | None = None
    sso_enabled: bool = False
    sso_provider: str | None = None
    created_at: datetime


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class ApiKeyResponse(BaseModel):
    id: str
    key_prefix: str
    scopes: list[str]
    name: str
    created_by: str
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked: bool
    created_at: datetime


class ApiKeyCreateResponse(ApiKeyResponse):
    key: str


class ClerkApiKeyResponse(BaseModel):
    api_key: str
    org_id: str
    org_name: str
    role: str = "admin"
    auth_mode: Literal["api_key", "sso_session"] = "api_key"
    expires_at: datetime | None = None


class SSOSettingsResponse(BaseModel):
    enabled: bool = False
    provider: str | None = None
    metadata_url: str | None = None
    metadata_xml: str | None = None
    entity_id: str | None = None
    domains: list[str] = Field(default_factory=list)
    default_role: Literal["admin", "operator", "viewer"] = "viewer"
    auto_join: bool = False


class SSOSettingsUpdateRequest(BaseModel):
    enabled: bool | None = None
    provider: str | None = Field(default=None, max_length=128)
    metadata_url: str | None = Field(default=None, max_length=1024)
    metadata_xml: str | None = Field(default=None, max_length=20_000)
    entity_id: str | None = Field(default=None, max_length=512)
    domains: list[str] | None = None
    default_role: Literal["admin", "operator", "viewer"] | None = None
    auto_join: bool | None = None

    @field_validator("domains")
    @classmethod
    def validate_domains(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        normalized: list[str] = []
        for domain in v:
            candidate = domain.strip().lower()
            if not candidate:
                continue
            if "." not in candidate or "@" in candidate or " " in candidate:
                raise ValueError("domains must contain valid email domains only.")
            normalized.append(candidate)
        return normalized


class AgentUsageResponse(BaseModel):
    agent_id: str
    total_evaluations: int
    share_pct: int = Field(..., ge=0, le=100)
    last_evaluated_at: datetime | None = None


class UsageResponse(BaseModel):
    org_id: str
    total_evaluations: int
    eval_limit: int
    eval_warning_threshold_pct: int = Field(..., ge=1, le=100)
    eval_soft_limit_enabled: bool
    usage_pct: int = Field(..., ge=0)
    quota_state: Literal["ok", "warning", "exceeded"]
    warning_message: str | None = None
    per_agent: list[AgentUsageResponse] = Field(default_factory=list)


class WebhookDeliveryResponse(BaseModel):
    id: str
    webhook_id: str
    org_id: str
    event: str
    payload: dict[str, object]
    status: str
    http_status: int | None
    attempts: int
    last_error: str | None
    created_at: datetime


_VALID_WEBHOOK_EVENTS = frozenset(
    [
        "approval.approved",
        "approval.rejected",
        "evaluation.completed",
        "policy.changed",
        "agent.updated",
    ]
)


def _validate_webhook_url(url: str) -> str:
    """M2: Ensure webhook URL uses http/https only — reject javascript:, data:, etc."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Webhook URL must use http or https scheme.")
    if not parsed.netloc:
        raise ValueError("Webhook URL must have a valid host.")
    return url


def _validate_webhook_events(events: list[str]) -> list[str]:
    """M7/H7: Validate event types in schema so they appear in OpenAPI spec as a 422."""
    unknown = set(events) - _VALID_WEBHOOK_EVENTS
    if unknown:
        raise ValueError(
            f"Unknown event types: {sorted(unknown)}. " f"Valid: {sorted(_VALID_WEBHOOK_EVENTS)}"
        )
    return events


class WebhookUpdate(BaseModel):
    url: str | None = Field(default=None, min_length=8, max_length=512)
    events: list[str] | None = None
    active: bool | None = None

    @field_validator("url")
    @classmethod
    def url_scheme(cls, v: str | None) -> str | None:
        if v is not None:
            _validate_webhook_url(v)
        return v

    @field_validator("events")
    @classmethod
    def validate_events(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            _validate_webhook_events(v)
        return v


class WebhookCreate(BaseModel):
    url: str = Field(..., min_length=8, max_length=512)
    events: list[str] = Field(
        default=["approval.approved", "approval.rejected"],
        min_length=1,
    )

    @field_validator("url")
    @classmethod
    def url_scheme(cls, v: str) -> str:
        return _validate_webhook_url(v)

    @field_validator("events")
    @classmethod
    def validate_events(cls, v: list[str]) -> list[str]:
        return _validate_webhook_events(v)


class WebhookResponse(BaseModel):
    id: str
    org_id: str
    url: str
    secret: str
    events: list[str]
    active: bool
    rotating_secret_expires_at: datetime | None = None
    created_at: datetime


class WebhookRotateSecretResponse(BaseModel):
    id: str
    new_secret: str
    rotating_secret_expires_at: datetime
    message: str


class WebhookTestResponse(BaseModel):
    delivery_id: str
    status: str
    http_status: int | None


class PolicyImportItem(BaseModel):
    """Single policy entry in a bulk import request."""

    name: str = Field(..., min_length=1, max_length=256)
    level: str = Field(..., pattern=r"^(org|project|agent)$")
    cedar_rule: str = Field(..., min_length=1)
    project_id: uuid.UUID | None = None
    agent_id: str | None = None
    active: bool = True
    state: str = Field(default="active", pattern=r"^(draft|active|archived)$")

    @field_validator("cedar_rule")
    @classmethod
    def validate_cedar(cls, v: str) -> str:
        return _validate_cedar_rule(v)


class PolicyImportRequest(BaseModel):
    """Bulk import request — JSON or YAML-decoded list of policies."""

    policies: list[PolicyImportItem] = Field(..., min_length=1)
    # dry_run=True validates and returns preview without writing to DB
    dry_run: bool = False
    # overwrite=True replaces existing policies with matching names
    overwrite: bool = False


class PolicyImportResult(BaseModel):
    """Per-policy result within a bulk import response."""

    name: str
    status: str  # "created" | "updated" | "skipped" | "error"
    policy_id: str | None = None
    error: str | None = None


class PolicyImportResponse(BaseModel):
    """Bulk import response."""

    dry_run: bool
    total: int
    created: int
    updated: int
    skipped: int
    errors: int
    results: list[PolicyImportResult]


class PolicyTemplateResponse(BaseModel):
    id: str
    name: str
    description: str
    category: str
    tags: list[str] = Field(default_factory=list)
    policies: list[PolicyImportItem] = Field(default_factory=list)


class PolicyTestCase(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    agent_id: str = Field(..., min_length=1, max_length=256)
    action: str = Field(..., min_length=1, max_length=256)
    resource: str = Field(..., min_length=1, max_length=512)
    context: dict[str, object] = Field(default_factory=dict)
    expected_decision: Literal["ALLOW", "DENY", "APPROVAL_REQUIRED"]


class PolicyTestSuiteRequest(BaseModel):
    policy_ids: list[str] | None = None
    test_cases: list[PolicyTestCase] = Field(..., max_length=100)


class PolicyTestCaseResult(BaseModel):
    name: str
    passed: bool
    actual_decision: str
    expected_decision: str
    reason: str
    latency_ms: float


class PolicyTestSuiteResponse(BaseModel):
    total: int
    passed: int
    failed: int
    results: list[PolicyTestCaseResult]
    duration_ms: float


class PolicyTestSuiteCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    test_cases: list[PolicyTestCase] = Field(..., max_length=100)


class PolicyTestSuiteRecordResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    test_cases: list[PolicyTestCase] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class HealthResponse(BaseModel):
    status: str


class VersionMetadataResponse(BaseModel):
    api_version: str
    min_supported_version: str
    deprecated_versions: list[str] = Field(default_factory=list)
    latest_version: str
    changelog_url: str


class CopilotMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class CopilotRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: str | None = None  # None = start a new conversation
    auto_confirm: bool = False
    # When confirming a preview, pass the original preview back so the backend
    # can create the resource directly without calling Claude again.
    confirm_preview: dict[str, object] | None = None


class CopilotPreview(BaseModel):
    resource_type: Literal["policy", "agent", "webhook"]
    data: dict[str, object]
    cedar_rule: str | None = None
    confirmation_prompt: str


class CopilotResponse(BaseModel):
    message: str
    action_type: Literal[
        "create_policy",
        "list_policies",
        "delete_policy",
        "register_agent",
        "list_agents",
        "create_webhook",
        "list_webhooks",
        "explain",
        "explain_policy",
        "sample",
        "general",
        "error",
        "confirm_pending",
        "confirmed",
        "cancelled",
    ]
    conversation_id: str = ""  # always returned; empty only on plan-gate error
    preview: CopilotPreview | None = None
    created_resource: dict[str, object] | None = None
    suggestions: list[str] | None = None
    cedar_validation_error: str | None = None
    cedar_valid: bool = True


class PolicyVersionResponse(BaseModel):
    id: str
    policy_id: str
    org_id: str
    cedar_rule: str
    name: str
    level: str
    state: str
    version: int
    created_at: datetime


class SimulateRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=256)
    action: str = Field(..., min_length=1, max_length=256)
    resource: str = Field(..., min_length=1, max_length=512)
    context: dict[str, object] = Field(default_factory=dict)

    @field_validator("agent_id", "action", "resource")
    @classmethod
    def strip_control_chars(cls, v: str) -> str:
        return _strip_ctrl(v)

    @field_validator("context")
    @classmethod
    def context_size_limit(cls, v: dict[str, object]) -> dict[str, object]:
        if len(v) > 50:
            raise ValueError("context must have at most 50 keys.")
        return v


class SimulateResponse(BaseModel):
    decision: str
    reason: str
    policy_id: str | None = None
    risk_score: int | None = None
    risk_level: str | None = None
    risk_factors: dict[str, int] | None = None
    compliance_findings: list[ComplianceFindingResponse] | None = None
    decision_trace: DecisionTrace


class ReplayRequest(BaseModel):
    policy_ids: list[str] | None = None


class ReplayResponse(BaseModel):
    eval_id: str
    original_decision: str
    replayed_decision: str
    changed: bool
    original_policy_source: str | None = None
    replayed_policy_source: str
    original_risk_score: int | None = None
    replayed_risk_score: int | None = None
    replayed_at: datetime


class EvaluationStreamEvent(BaseModel):
    eval_id: str
    agent_id: str
    action: str
    resource: str
    decision: str
    risk_score: int | None = None
    risk_level: str | None = None
    policy_source: str
    timestamp: datetime


class ErrorResponse(BaseModel):
    error: str
    message: str
    upgrade_url: str | None = None


class ConversationMessageOut(BaseModel):
    id: str
    role: str
    content: str
    action_type: str | None = None
    metadata: dict[str, object] | None = None
    created_at: datetime


class ConversationSummary(BaseModel):
    id: str
    title: str
    message_count: int
    updated_at: datetime


class ConversationDetail(BaseModel):
    id: str
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime
    messages: list[ConversationMessageOut]


# ── Org member (team invite) schemas ─────────────────────────────────────────

_VALID_MEMBER_ROLES = frozenset({"admin", "operator", "viewer"})


class OrgMemberResponse(BaseModel):
    id: str
    org_id: str
    email: str
    role: str = Field(..., description="admin | operator | viewer")
    status: str = Field(..., description="invited | active | revoked")
    invited_by: str | None = None
    joined_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class OrgMemberInviteRequest(BaseModel):
    email: str = Field(
        ...,
        min_length=3,
        max_length=256,
        description="Email address of the person to invite.",
        examples=["ops@example.com"],
    )
    role: str = Field(
        default="viewer",
        pattern=r"^(admin|operator|viewer)$",
        description="Role to assign: admin | operator | viewer",
    )


class OrgMemberUpdateRequest(BaseModel):
    role: str = Field(
        ..., pattern=r"^(admin|operator|viewer)$", description="New role: admin | operator | viewer"
    )
