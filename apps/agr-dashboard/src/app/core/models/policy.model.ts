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

export interface PolicyTestCase {
  name: string;
  agent_id: string;
  action: string;
  resource: string;
  context: Record<string, unknown>;
  expected_decision: 'ALLOW' | 'DENY' | 'APPROVAL_REQUIRED';
}

export interface PolicyTestCaseResult {
  name: string;
  passed: boolean;
  actual_decision: string;
  expected_decision: string;
  reason: string;
  latency_ms: number;
}

export interface PolicyTestSuite {
  id: string;
  name: string;
  description: string | null;
  test_cases: PolicyTestCase[];
  created_at: string;
  updated_at: string;
}

export interface PolicyTestSuiteRunResult {
  total: number;
  passed: number;
  failed: number;
  results: PolicyTestCaseResult[];
  duration_ms: number;
}
