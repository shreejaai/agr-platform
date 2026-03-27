export interface EvaluationResult {
  /** "ALLOW" | "DENY" | "APPROVAL_REQUIRED" */
  readonly decision: string;
  readonly reason: string;
  readonly policyId: string | null;
  readonly approvalId: string | null;
  readonly latencyMs: number;
  readonly evalId: string;
  /** Risk score 0–100 (null if risk scoring not configured) */
  readonly riskScore: number | null;
  /** "LOW" | "MEDIUM" | "HIGH" | null */
  readonly riskLevel: string | null;
  /** Factor breakdown — e.g. { action_severity: 40, environment: 30 } */
  readonly riskFactors: Record<string, number> | null;
  /** Compliance plugin findings */
  readonly complianceFindings: ComplianceFinding[] | null;
  /** true when decision === "ALLOW" */
  readonly allowed: boolean;
  /** true when decision === "DENY" */
  readonly denied: boolean;
  /** true when decision === "APPROVAL_REQUIRED" */
  readonly requiresApproval: boolean;
}

export interface ComplianceFinding {
  plugin: string;
  standard: string;
  rule_id: string;
  severity: string;
  message: string;
  passed: boolean;
  remediation_steps?: string[];
  severity_level?: "low" | "medium" | "high" | "critical";
  compliance_score?: number;
}

/** Raw shape of the API JSON response — snake_case as returned by the server. */
export interface EvaluateApiResponse {
  decision: string;
  reason: string;
  policy_id: string | null;
  approval_id: string | null;
  latency_ms: number;
  eval_id: string;
  risk_score: number | null;
  risk_level: string | null;
  risk_factors: Record<string, number> | null;
  compliance_findings: ComplianceFinding[] | null;
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

export interface PolicyImportItem {
  name: string;
  level: 'org' | 'project' | 'agent';
  cedar_rule: string;
  active?: boolean;
  agent_id?: string | null;
  project_id?: string | null;
}

export interface PolicyImportRequest {
  policies: PolicyImportItem[];
  overwrite?: boolean;
  dry_run?: boolean;
}

export interface PolicyImportResult {
  name: string;
  status: 'created' | 'updated' | 'skipped' | 'error';
  policy_id: string | null;
  error: string | null;
}

export interface PolicyImportResponse {
  dry_run: boolean;
  total: number;
  created: number;
  updated: number;
  skipped: number;
  errors: number;
  results: PolicyImportResult[];
}
