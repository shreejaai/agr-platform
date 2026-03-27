/**
 * AGR API test client for Playwright.
 * Wraps the AGR REST API for use in domain scenario tests.
 * Used by all domain spec files.
 */

import { APIRequestContext } from "@playwright/test";

export interface EvaluateRequest {
  agent_id: string;
  action: string;
  resource: string;
  context: Record<string, unknown>;
  approver_email?: string;
}

export interface EvaluateResponse {
  decision: "ALLOW" | "DENY" | "APPROVAL_REQUIRED";
  reason: string;
  policy_id: string | null;
  approval_id: string | null;
  risk_score: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  eval_id: string;
  latency_ms: number;
  engine_mode: string;
  compliance_findings: ComplianceFinding[];
  decision_trace: DecisionTrace;
}

export interface ComplianceFinding {
  rule_id: string;
  severity: string;
  message: string;
  remediation: string;
}

export interface DecisionTrace {
  policy_source: string;
  matched_policy_id: string | null;
  cedar_decision: string;
  risk_override: boolean;
  fallback_used: boolean;
  fallback_reason: string | null;
}

export interface PolicyCreateRequest {
  name: string;
  cedar_rule: string;
  level: "org" | "agent" | "resource";
  state?: "draft" | "active";
  agent_id?: string;
}

export interface PolicyResponse {
  id: string;
  name: string;
  cedar_rule: string;
  level: string;
  state: string;
  version: number;
  created_at: string;
}

export class AGRTestClient {
  private baseURL: string;
  private apiKey: string;
  private request: APIRequestContext;

  constructor(request: APIRequestContext, baseURL?: string, apiKey?: string) {
    this.request = request;
    this.baseURL = baseURL ?? process.env["AGR_BASE_URL"] ?? "http://localhost:8000";
    this.apiKey = apiKey ?? process.env["AGR_API_KEY"] ?? "";

    if (!this.apiKey) {
      throw new Error(
        "AGR_API_KEY environment variable is required. " +
        "Set it in your .env.test file or export AGR_API_KEY=agr_sk_..."
      );
    }
  }

  private headers(): Record<string, string> {
    return {
      Authorization: `Bearer ${this.apiKey}`,
      "Content-Type": "application/json",
    };
  }

  async evaluate(req: EvaluateRequest): Promise<EvaluateResponse> {
    const res = await this.request.post(`${this.baseURL}/v1/evaluate`, {
      headers: this.headers(),
      data: req,
    });

    if (!res.ok()) {
      const body = await res.text();
      throw new Error(`AGR evaluate failed ${res.status()}: ${body}`);
    }

    return res.json() as Promise<EvaluateResponse>;
  }

  async createPolicy(policy: PolicyCreateRequest): Promise<PolicyResponse> {
    const res = await this.request.post(`${this.baseURL}/v1/policies`, {
      headers: this.headers(),
      data: { ...policy, state: policy.state ?? "active" },
    });

    if (!res.ok()) {
      const body = await res.text();
      throw new Error(`AGR createPolicy failed ${res.status()}: ${body}`);
    }

    return res.json() as Promise<PolicyResponse>;
  }

  async activatePolicy(policyId: string): Promise<void> {
    const res = await this.request.patch(
      `${this.baseURL}/v1/policies/${policyId}/activate`,
      { headers: this.headers() }
    );
    if (!res.ok()) {
      throw new Error(`AGR activatePolicy failed ${res.status()}`);
    }
  }

  async deletePolicy(policyId: string): Promise<void> {
    const res = await this.request.delete(
      `${this.baseURL}/v1/policies/${policyId}`,
      { headers: this.headers() }
    );
    if (!res.ok() && res.status() !== 404) {
      throw new Error(`AGR deletePolicy failed ${res.status()}`);
    }
  }

  async listPolicies(): Promise<PolicyResponse[]> {
    const res = await this.request.get(`${this.baseURL}/v1/policies`, {
      headers: this.headers(),
    });
    if (!res.ok()) throw new Error(`AGR listPolicies failed ${res.status()}`);
    const body = await res.json() as { items: PolicyResponse[] };
    return body.items;
  }

  async deleteAllPolicies(): Promise<void> {
    const policies = await this.listPolicies();
    await Promise.all(policies.map((p) => this.deletePolicy(p.id)));
  }

  async healthCheck(): Promise<boolean> {
    const res = await this.request.get(`${this.baseURL}/health`);
    return res.ok();
  }
}
