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
  state?: 'draft' | 'active' | 'archived';
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

export interface PolicyImportItem {
  name: string;
  level: 'org' | 'project' | 'agent';
  cedar_rule: string;
  active?: boolean;
  state?: 'draft' | 'active' | 'archived';
  agent_id?: string | null;
  project_id?: string | null;
}

export interface PolicyImportRequest {
  policies: PolicyImportItem[];
  dry_run?: boolean;
  overwrite?: boolean;
}

export interface PolicyImportResult {
  name: string;
  status: 'created' | 'updated' | 'skipped' | 'error';
  policy_id?: string | null;
  error?: string | null;
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

export interface PolicyTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  policies: PolicyImportItem[];
}
