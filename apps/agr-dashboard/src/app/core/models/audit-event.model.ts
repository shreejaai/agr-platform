export type AuditEventType =
  | 'TOOL_ALLOW'
  | 'TOOL_DENY'
  | 'APPROVAL_REQUESTED'
  | 'APPROVAL_APPROVED'
  | 'APPROVAL_REJECTED';

/** Typed payload fields surfaced in the audit detail panel. */
export interface AuditPayload {
  eval_id?: string;
  cached?: boolean;
  policy_source?: string;
  fallback_used?: boolean;
  fallback_reason?: string;
  no_policy_fallback?: boolean;
  no_policy_action?: string;
  risk_score?: number;
  risk_level?: string;
  risk_factors?: Record<string, number>;
  compliance_findings?: unknown[];
  compliance_blocked?: boolean;
  compliance_block_reason?: string;
  context?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface AuditEvent {
  id: string;
  org_id: string;
  sequence_num: number;
  event_type: AuditEventType;
  agent_id: string;
  action: string;
  resource: string;
  decision: string;
  policy_id: string | null;
  approval_id: string | null;
  payload: AuditPayload | null;
  prev_hash: string | null;
  entry_hash: string;
  recorded_at: string;
}

export interface AuditFilter {
  event_type?: AuditEventType | '';
  agent_id?: string;
  action?: string;
  decision?: string;
  policy_id?: string;
  /** Single-day filter — maps to start_date on the API (YYYY-MM-DD). */
  date?: string;
  start_date?: string;
  end_date?: string;
  limit?: number;
  offset?: number;
}
