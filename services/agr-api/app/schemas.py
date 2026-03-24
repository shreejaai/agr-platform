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


class EvaluateRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=256)
    action: str = Field(..., min_length=1, max_length=256)
    resource: str = Field(..., min_length=1, max_length=512)
    # M6: limit context to 50 keys to prevent DoS via huge payloads
    context: dict[str, object] = Field(default_factory=dict)
    approver_email: str | None = Field(default=None, max_length=256)

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


class EvaluateResponse(BaseModel):
    decision: str
    reason: str
    policy_id: str | None = None
    approval_id: str | None = None
    latency_ms: float
    eval_id: str
    risk_score: int | None = None
    risk_level: str | None = None
    risk_factors: dict[str, int] | None = None
    compliance_findings: list[dict[str, object]] | None = None


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

    @field_validator("cedar_rule")
    @classmethod
    def validate_cedar(cls, v: str) -> str:
        return _validate_cedar_rule(v)


class PolicyUpdate(BaseModel):
    cedar_rule: str | None = None
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
    created_at: datetime
    updated_at: datetime


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
    created_at: datetime


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


class AgentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=1024)
    framework: str | None = Field(default=None, max_length=64)
    active: bool | None = None


class AgentResponse(BaseModel):
    id: str
    org_id: str
    agent_id: str
    metadata: dict[str, object] | None
    active: bool
    created_at: datetime
    updated_at: datetime


class ApprovalEscalateRequest(BaseModel):
    approver_email: str = Field(..., min_length=1, max_length=256)


class AuditVerifyResponse(BaseModel):
    valid: bool
    total: int
    first_invalid_sequence: int | None = None


class OrgMeResponse(BaseModel):
    id: str
    name: str
    slug: str | None
    plan: str
    eval_count: int
    eval_limit: int
    eval_week_start: datetime | None = None
    created_at: datetime


class ClerkApiKeyResponse(BaseModel):
    api_key: str
    org_id: str
    org_name: str


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


_VALID_WEBHOOK_EVENTS = frozenset(["approval.approved", "approval.rejected"])


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
    created_at: datetime


class PolicyImportItem(BaseModel):
    """Single policy entry in a bulk import request."""

    name: str = Field(..., min_length=1, max_length=256)
    level: str = Field(..., pattern=r"^(org|project|agent)$")
    cedar_rule: str = Field(..., min_length=1)
    project_id: uuid.UUID | None = None
    agent_id: str | None = None
    active: bool = True

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


class HealthResponse(BaseModel):
    status: str


class CopilotMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class CopilotRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: str | None = None  # None = start a new conversation
    auto_confirm: bool = False
    # When confirming a preview, pass the original preview back so the backend
    # can create the resource directly without calling Claude again.
    confirm_preview: dict | None = None


class CopilotPreview(BaseModel):
    resource_type: Literal["policy", "agent", "webhook"]
    data: dict
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
        "sample",
        "general",
        "error",
        "confirm_pending",
        "confirmed",
        "cancelled",
    ]
    conversation_id: str = ""  # always returned; empty only on plan-gate error
    preview: CopilotPreview | None = None
    created_resource: dict | None = None
    suggestions: list[str] | None = None


class ErrorResponse(BaseModel):
    error: str
    message: str
    upgrade_url: str | None = None


class ConversationMessageOut(BaseModel):
    id: str
    role: str
    content: str
    action_type: str | None = None
    metadata: dict | None = None
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
