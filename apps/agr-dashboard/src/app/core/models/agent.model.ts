export interface Agent {
  id: string;
  org_id: string;
  agent_id: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

/** Friendly form type used by the dashboard (converted to AgentRegisterRequest by AgentService). */
export interface AgentRegister {
  agent_id: string;
  name: string;
  description?: string;
  framework?: string;
}

/** Raw API request body sent to POST /v1/agents/register. */
export interface AgentRegisterRequest {
  agent_id: string;
  metadata?: Record<string, unknown>;
}

/** Helpers to extract display fields from metadata. */
export function agentName(a: Agent): string {
  return (a.metadata?.['name'] as string | undefined) || a.agent_id;
}

export function agentFramework(a: Agent): string {
  return (a.metadata?.['framework'] as string | undefined) || '—';
}

export function agentDescription(a: Agent): string | undefined {
  return a.metadata?.['description'] as string | undefined;
}
