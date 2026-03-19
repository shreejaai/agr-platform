export interface Agent {
  id: string;
  org_id: string;
  agent_id: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface AgentRegisterRequest {
  agent_id: string;
  metadata?: Record<string, unknown>;
}
