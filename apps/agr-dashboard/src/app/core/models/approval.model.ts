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
  created_at: string;
}

export interface ApprovalDecideRequest {
  decision: 'approved' | 'rejected';
  decided_by?: string;
  reason?: string;
}
