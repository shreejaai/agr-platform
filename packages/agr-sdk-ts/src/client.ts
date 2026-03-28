import { AGRAuthError, AGRError, AGRRateLimitError } from "./errors.js";
import type {
  AgentApiResponse,
  ApprovalApiResponse,
  ApprovalResult,
  EvaluateApiResponse,
  EvaluationResult,
  PolicyImportRequest,
  PolicyImportResponse,
  PolicyImportItem,
} from "./types.js";

export interface AGRClientOptions {
  /** API key. Falls back to AGR_API_KEY env var. */
  apiKey?: string;
  /** Base URL of the AGR API. Defaults to https://api.agr.dev */
  baseUrl?: string;
  /** Request timeout in milliseconds. Defaults to 10000. */
  timeout?: number;
}

export interface WaitForApprovalOptions {
  /** Polling interval in milliseconds. Defaults to 2000. */
  pollInterval?: number;
  /** Total timeout in milliseconds. Defaults to 3600000 (1 hour). */
  timeout?: number;
}

const DEFAULT_BASE_URL = "https://api.agr.dev";
const DEFAULT_TIMEOUT_MS = 10_000;
const DEFAULT_POLL_INTERVAL_MS = 2_000;
const DEFAULT_APPROVAL_TIMEOUT_MS = 3_600_000;
const SDK_VERSION = "0.1.0";

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function makeEvaluationResult(data: EvaluateApiResponse): EvaluationResult {
  return {
    decision: data.decision,
    reason: data.reason,
    policyId: data.policy_id,
    approvalId: data.approval_id,
    latencyMs: data.latency_ms,
    evalId: data.eval_id,
    riskScore: data.risk_score ?? null,
    riskLevel: data.risk_level ?? null,
    riskFactors: data.risk_factors ?? null,
    complianceFindings: data.compliance_findings ?? null,
    allowed: data.decision === "ALLOW",
    denied: data.decision === "DENY",
    requiresApproval: data.decision === "APPROVAL_REQUIRED",
  };
}

function makeApprovalResult(
  approvalId: string,
  data: ApprovalApiResponse,
): ApprovalResult {
  return {
    approvalId,
    status: data.status as "approved" | "rejected" | "expired",
    decidedBy: data.decided_by ?? undefined,
    decidedAt: data.decision_at ?? undefined,
  };
}

export class AGRClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly timeoutMs: number;

  constructor(options: AGRClientOptions = {}) {
    const apiKey =
      options.apiKey ??
      (typeof process !== "undefined" ? process.env["AGR_API_KEY"] : undefined) ??
      "";
    if (!apiKey) {
      throw new AGRError(
        "API key is required. Pass apiKey or set AGR_API_KEY environment variable.",
      );
    }
    this.apiKey = apiKey;
    this.baseUrl = (options.baseUrl ?? DEFAULT_BASE_URL).replace(/\/$/, "");
    this.timeoutMs = options.timeout ?? DEFAULT_TIMEOUT_MS;
  }

  // ---------------------------------------------------------------------------
  // Private HTTP helper
  // ---------------------------------------------------------------------------

  private async _request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${this.apiKey}`,
          "Content-Type": "application/json",
          Accept: "application/json",
          "AGR-Client-Version": `ts-sdk/${SDK_VERSION}`,
          "Accept-Version": "application/vnd.agr.v1+json",
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        throw new AGRError(`Request timed out after ${this.timeoutMs}ms.`);
      }
      throw new AGRError(
        `Network error: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      clearTimeout(timer);
    }

    if (response.status === 401) {
      const data = await response.json().catch(() => ({})) as Record<string, string>;
      throw new AGRAuthError(
        data["message"] ??
          "Unauthorized. Check your API key at https://dashboard.agr.dev/settings",
      );
    }

    if (response.status === 429) {
      const data = await response.json().catch(() => ({})) as Record<string, string>;
      throw new AGRRateLimitError(
        data["message"] ?? "Rate limit exceeded.",
        data["upgrade_url"],
      );
    }

    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new AGRError(`AGR API error (${response.status}): ${text}`, response.status);
    }

    return response.json() as Promise<T>;
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /**
   * Evaluate an agent action against Cedar policies.
   *
   * @throws AGRAuthError on 401
   * @throws AGRRateLimitError on 429
   * @throws AGRError on other failures
   */
  async evaluate(
    agent: string,
    action: string,
    resource: string,
    context: Record<string, unknown> = {},
  ): Promise<EvaluationResult> {
    const data = await this._request<EvaluateApiResponse>("POST", "/v1/evaluate", {
      agent_id: agent,
      action,
      resource,
      context,
    });
    return makeEvaluationResult(data);
  }

  /**
   * Poll until a pending approval is resolved.
   *
   * @returns true if approved, false if rejected
   * @throws Error if not resolved within timeout
   * @throws AGRError on unexpected API failures
   */
  async waitForApproval(
    approvalId: string,
    options: WaitForApprovalOptions = {},
  ): Promise<boolean> {
    const pollInterval = options.pollInterval ?? DEFAULT_POLL_INTERVAL_MS;
    const timeoutMs = options.timeout ?? DEFAULT_APPROVAL_TIMEOUT_MS;
    const started = Date.now();

    while (true) {
      if (Date.now() - started >= timeoutMs) {
        throw new Error(
          `Approval ${approvalId} not resolved within ${timeoutMs}ms.`,
        );
      }

      const data = await this._request<ApprovalApiResponse>(
        "GET",
        `/v1/approvals/${approvalId}`,
      );

      if (data.status === "approved") return true;
      if (data.status === "rejected") return false;

      await delay(pollInterval);
    }
  }

  onApprovalResolved(
    approvalId: string,
    callback: (result: ApprovalResult) => void,
    options: { pollInterval?: number; timeout?: number } = {},
  ): () => void {
    const pollInterval = options.pollInterval ?? DEFAULT_POLL_INTERVAL_MS;
    const timeoutMs = options.timeout ?? DEFAULT_APPROVAL_TIMEOUT_MS;
    const started = Date.now();
    let cancelled = false;

    const tick = async (): Promise<void> => {
      if (cancelled) return;
      if (Date.now() - started >= timeoutMs) {
        cancelled = true;
        clearInterval(interval);
        callback({ approvalId, status: "expired" });
        return;
      }

      try {
        const data = await this._request<ApprovalApiResponse>(
          "GET",
          `/v1/approvals/${approvalId}`,
        );
        if (data.status !== "pending") {
          cancelled = true;
          clearInterval(interval);
          callback(makeApprovalResult(approvalId, data));
        }
      } catch {
        cancelled = true;
        clearInterval(interval);
      }
    };

    const interval = setInterval(() => {
      void tick();
    }, pollInterval);
    void tick();

    return (): void => {
      cancelled = true;
      clearInterval(interval);
    };
  }

  /**
   * Register an agent with AGR. Upserts on (org, agent_id).
   */
  async registerAgent(
    agentId: string,
    metadata: Record<string, unknown> = {},
  ): Promise<AgentApiResponse> {
    return this._request<AgentApiResponse>("POST", "/v1/agents/register", {
      agent_id: agentId,
      metadata,
    });
  }

  /**
   * Bulk-import policies.
   * Each item requires: name, level ("org"|"project"|"agent"), cedar_rule.
   */
  async importPolicies(request: PolicyImportRequest): Promise<PolicyImportResponse> {
    return this._request<PolicyImportResponse>("POST", "/v1/policies/import", request);
  }

  /**
   * Export all org policies. Returns array of PolicyImportItem-compatible objects.
   */
  async exportPolicies(activeOnly = true): Promise<PolicyImportItem[]> {
    const qs = activeOnly ? "?active_only=true" : "?active_only=false";
    return this._request<PolicyImportItem[]>("GET", `/v1/policies/export${qs}`);
  }

  // ── Audit ────────────────────────────────────────────────────────────────

  /** Fetch audit events with optional filters. */
  async getAuditEvents(params: {
    event_type?: string;
    agent_id?: string;
    action?: string;
    resource?: string;
    decision?: string;
    start_date?: string;
    end_date?: string;
    limit?: number;
    offset?: number;
  } = {}): Promise<Record<string, unknown>[]> {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined) qs.set(k, String(v));
    }
    const query = qs.toString() ? `?${qs.toString()}` : "";
    return this._request<Record<string, unknown>[]>("GET", `/v1/audit${query}`);
  }

  /** POST /v1/audit/search — structured filter query. */
  async searchAudit(filters: Record<string, unknown>): Promise<Record<string, unknown>[]> {
    return this._request<Record<string, unknown>[]>("POST", "/v1/audit/search", filters);
  }

  // ── Risk config ──────────────────────────────────────────────────────────

  /** Return current per-org risk scoring configuration. */
  async getRiskConfig(): Promise<Record<string, unknown>> {
    return this._request<Record<string, unknown>>("GET", "/v1/org/risk-config");
  }

  /** Update per-org risk scoring weights and thresholds. */
  async updateRiskConfig(updates: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this._request<Record<string, unknown>>("PUT", "/v1/org/risk-config", updates);
  }

  // ── Compliance ───────────────────────────────────────────────────────────

  /** Return aggregated compliance posture for the last N days. */
  async getComplianceSummary(periodDays = 7): Promise<Record<string, unknown>> {
    return this._request<Record<string, unknown>>(
      "GET",
      `/v1/compliance/summary?period_days=${periodDays}`,
    );
  }

  /**
   * No-op. Kept for API parity with the Python SDK.
   * The fetch-based client has no persistent connections to close.
   */
  close(): void {
    // no-op
  }
}
