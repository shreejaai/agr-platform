import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class EvaluateRequest(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=256)
    action: str = Field(..., min_length=1, max_length=256)
    resource: str = Field(..., min_length=1, max_length=512)
    context: dict[str, object] = Field(default_factory=dict)
    approver_email: str | None = Field(default=None, max_length=256)


class EvaluateResponse(BaseModel):
    decision: str
    reason: str
    policy_id: str | None = None
    approval_id: str | None = None
    latency_ms: float
    eval_id: str


class PolicyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    level: str = Field(..., pattern=r"^(org|project|agent)$")
    cedar_rule: str = Field(..., min_length=1)
    project_id: uuid.UUID | None = None
    agent_id: str | None = None


class PolicyUpdate(BaseModel):
    cedar_rule: str | None = None
    active: bool | None = None
    name: str | None = None


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


class WebhookUpdate(BaseModel):
    url: str | None = Field(default=None, min_length=8, max_length=512)
    events: list[str] | None = None
    active: bool | None = None


class WebhookCreate(BaseModel):
    url: str = Field(..., min_length=8, max_length=512)
    events: list[str] = Field(
        default=["approval.approved", "approval.rejected"],
        min_length=1,
    )


class WebhookResponse(BaseModel):
    id: str
    org_id: str
    url: str
    secret: str
    events: list[str]
    active: bool
    created_at: datetime


class HealthResponse(BaseModel):
    status: str


class ErrorResponse(BaseModel):
    error: str
    message: str
    upgrade_url: str | None = None
