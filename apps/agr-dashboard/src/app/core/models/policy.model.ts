export interface Policy {
  id: string;
  org_id: string;
  project_id: string | null;
  agent_id: string | null;
  name: string;
  level: 'org' | 'project' | 'agent';
  cedar_rule: string;
  version: number;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface PolicyCreate {
  name: string;
  level: 'org' | 'project' | 'agent';
  cedar_rule: string;
  project_id?: string;
  agent_id?: string;
}

export interface PolicyUpdate {
  name?: string;
  cedar_rule?: string;
  active?: boolean;
}
