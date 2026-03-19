export type AuditEventType =
  | 'TOOL_ALLOW'
  | 'TOOL_DENY'
  | 'APPROVAL_REQUESTED'
  | 'APPROVAL_APPROVED'
  | 'APPROVAL_REJECTED';

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
  payload: Record<string, unknown> | null;
  prev_hash: string | null;
  entry_hash: string;
  recorded_at: string;
}

export interface AuditFilter {
  event_type?: AuditEventType | '';
  agent_id?: string;
  start_date?: string;
  end_date?: string;
  limit?: number;
  offset?: number;
}
