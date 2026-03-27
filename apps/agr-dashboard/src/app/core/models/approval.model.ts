export interface Approval {
  id: string;
  org_id: string;
  agent_id: string;
  action: string;
  resource: string;
  context: Record<string, unknown> | null;
  status: 'pending' | 'approved' | 'rejected';
  approver_email: string | null;
  decision_at: string | null;
  expires_at: string;
  quorum_type: 'any' | 'all';
  sla_hours: number | null;
  escalation_email: string | null;
  created_at: string;
  workflow_mode: 'temporal' | 'db_only';
  temporal_run_id: string | null;
  workflow_status: 'running' | 'completed' | 'failed' | 'escalated';
  workflow_last_error: string | null;
  workflow_last_transition_at: string | null;
  workflow_fallback_mode: string;
  workflow_escalated_at: string | null;
}

export interface ApprovalStep {
  id: string;
  approval_id: string;
  approver_email: string;
  status: 'pending' | 'approved' | 'rejected';
  decided_at: string | null;
  created_at: string;
}

export interface ApprovalDecideRequest {
  decision: 'approved' | 'rejected';
  decided_by?: string;
  reason?: string;
}
