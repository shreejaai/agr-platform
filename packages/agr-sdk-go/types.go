package agr

import "time"

type EvaluateRequest struct {
	AgentID       string                 `json:"agent_id"`
	Action        string                 `json:"action"`
	Resource      string                 `json:"resource"`
	Context       map[string]any         `json:"context,omitempty"`
	ApproverEmail string                 `json:"approver_email,omitempty"`
}

type SimulateRequest struct {
	AgentID  string                 `json:"agent_id"`
	Action   string                 `json:"action"`
	Resource string                 `json:"resource"`
	Context  map[string]any         `json:"context,omitempty"`
}

type EvaluateResponse struct {
	Decision           string                `json:"decision"`
	Reason             string                `json:"reason"`
	PolicyID           string                `json:"policy_id"`
	ApprovalID         string                `json:"approval_id"`
	RiskScore          *int                  `json:"risk_score"`
	RiskLevel          string                `json:"risk_level"`
	LatencyMs          float64               `json:"latency_ms"`
	EvalID             string                `json:"eval_id"`
	EngineMode         string                `json:"engine_mode"`
	ComplianceFindings []map[string]any      `json:"compliance_findings"`
	DecisionTrace      *DecisionTrace        `json:"decision_trace"`
}

type DecisionTrace struct {
	PolicySource    string `json:"policy_source"`
	MatchedPolicyID string `json:"matched_policy_id"`
	CedarDecision   string `json:"cedar_decision"`
	RiskOverride    bool   `json:"risk_override"`
	FallbackUsed    bool   `json:"fallback_used"`
	FallbackReason  string `json:"fallback_reason"`
}

type ApprovalResponse struct {
	ID           string    `json:"id"`
	Status       string    `json:"status"`
	WorkflowMode string    `json:"workflow_mode"`
	CreatedAt    time.Time `json:"created_at"`
	ExpiresAt    time.Time `json:"expires_at"`
}

type RegisterAgentRequest struct {
	AgentID      string         `json:"agent_id"`
	Name         string         `json:"name,omitempty"`
	Owner        string         `json:"owner,omitempty"`
	Framework    string         `json:"framework,omitempty"`
	Environment  string         `json:"environment,omitempty"`
	Capabilities []string       `json:"capabilities,omitempty"`
	Metadata     map[string]any `json:"metadata,omitempty"`
}

type WaitOptions struct {
	PollInterval time.Duration
	Timeout      time.Duration
}

func (w WaitOptions) normalized() WaitOptions {
	if w.PollInterval <= 0 {
		w.PollInterval = 2 * time.Second
	}
	if w.Timeout <= 0 {
		w.Timeout = time.Hour
	}
	return w
}
