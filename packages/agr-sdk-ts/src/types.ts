export interface EvaluationResult {
  /** "ALLOW" | "DENY" | "APPROVAL_REQUIRED" */
  readonly decision: string;
  readonly reason: string;
  readonly policyId: string | null;
  readonly approvalId: string | null;
  readonly latencyMs: number;
  readonly evalId: string;
  /** true when decision === "ALLOW" */
  readonly allowed: boolean;
  /** true when decision === "DENY" */
  readonly denied: boolean;
  /** true when decision === "APPROVAL_REQUIRED" */
  readonly requiresApproval: boolean;
}

/** Raw shape of the API JSON response — snake_case as returned by the server. */
export interface EvaluateApiResponse {
  decision: string;
  reason: string;
  policy_id: string | null;
  approval_id: string | null;
  latency_ms: number;
  eval_id: string;
}

export interface ApprovalApiResponse {
  id: string;
  status: string;
  agent_id: string;
  action: string;
  resource: string;
}

export interface AgentApiResponse {
  id: string;
  org_id: string;
  agent_id: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}
