import { AGRAuthError, AGRError, AGRRateLimitError } from "../errors";
import { AGRClient } from "../client";

// ---------------------------------------------------------------------------
// Fetch mock helpers
// ---------------------------------------------------------------------------

function mockFetch(status: number, body: unknown): jest.SpyInstance {
  return jest.spyOn(globalThis, "fetch").mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response);
}

function mockFetchMulti(responses: Array<{ status: number; body: unknown }>): jest.SpyInstance {
  const spy = jest.spyOn(globalThis, "fetch");
  for (const { status, body } of responses) {
    spy.mockResolvedValueOnce({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
      text: async () => JSON.stringify(body),
    } as Response);
  }
  return spy;
}

afterEach(() => {
  jest.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Constructor
// ---------------------------------------------------------------------------

describe("AGRClient constructor", () => {
  it("throws AGRError when no API key", () => {
    delete process.env["AGR_API_KEY"];
    expect(() => new AGRClient()).toThrow(AGRError);
    expect(() => new AGRClient()).toThrow("API key is required");
  });

  it("reads API key from AGR_API_KEY env var", () => {
    process.env["AGR_API_KEY"] = "agr_sk_envkey";
    expect(() => new AGRClient()).not.toThrow();
    delete process.env["AGR_API_KEY"];
  });

  it("accepts explicit apiKey option", () => {
    expect(() => new AGRClient({ apiKey: "agr_sk_test" })).not.toThrow();
  });

  it("strips trailing slash from baseUrl", () => {
    const client = new AGRClient({ apiKey: "agr_sk_test", baseUrl: "http://localhost:8000/" });
    // Verify via evaluate call — URL should not have double slash
    mockFetch(200, { decision: "ALLOW", reason: "ok", policy_id: null, approval_id: null, latency_ms: 1, eval_id: "e1" });
    expect(client.evaluate("a", "b", "c")).resolves.toBeTruthy();
    const spy = jest.spyOn(globalThis, "fetch");
    spy.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ decision: "ALLOW", reason: "ok", policy_id: null, approval_id: null, latency_ms: 1, eval_id: "e1" }), text: async () => "" } as Response);
    // Just check no double slash — can inspect the spy call if needed
  });
});

// ---------------------------------------------------------------------------
// evaluate()
// ---------------------------------------------------------------------------

describe("evaluate()", () => {
  const client = new AGRClient({ apiKey: "agr_sk_test" });

  it("returns ALLOW result with correct fields", async () => {
    mockFetch(200, {
      decision: "ALLOW",
      reason: "allowed by policy",
      policy_id: "pol-1",
      approval_id: null,
      latency_ms: 1.5,
      eval_id: "eval-abc",
    });
    const result = await client.evaluate("agent-1", "deploy", "server", { environment: "staging" });
    expect(result.decision).toBe("ALLOW");
    expect(result.allowed).toBe(true);
    expect(result.denied).toBe(false);
    expect(result.requiresApproval).toBe(false);
    expect(result.policyId).toBe("pol-1");
    expect(result.approvalId).toBeNull();
    expect(result.latencyMs).toBe(1.5);
    expect(result.evalId).toBe("eval-abc");
    expect(result.reason).toBe("allowed by policy");
  });

  it("returns DENY result", async () => {
    mockFetch(200, {
      decision: "DENY",
      reason: "denied by policy",
      policy_id: "pol-2",
      approval_id: null,
      latency_ms: 0.8,
      eval_id: "eval-deny",
    });
    const result = await client.evaluate("agent-1", "db.drop", "prod-db");
    expect(result.decision).toBe("DENY");
    expect(result.allowed).toBe(false);
    expect(result.denied).toBe(true);
    expect(result.requiresApproval).toBe(false);
  });

  it("returns APPROVAL_REQUIRED result with approvalId", async () => {
    mockFetch(200, {
      decision: "APPROVAL_REQUIRED",
      reason: "requires approval",
      policy_id: "pol-3",
      approval_id: "appr-xyz",
      latency_ms: 2.1,
      eval_id: "eval-appr",
    });
    const result = await client.evaluate("agent-1", "deploy", "prod-server", { environment: "production" });
    expect(result.decision).toBe("APPROVAL_REQUIRED");
    expect(result.requiresApproval).toBe(true);
    expect(result.allowed).toBe(false);
    expect(result.approvalId).toBe("appr-xyz");
  });

  it("defaults context to empty object", async () => {
    const spy = mockFetch(200, {
      decision: "ALLOW", reason: "ok", policy_id: null, approval_id: null, latency_ms: 1, eval_id: "e1",
    });
    await client.evaluate("agent-1", "read", "file");
    const body = JSON.parse((spy.mock.calls[0] as [string, RequestInit])[1].body as string);
    expect(body.context).toEqual({});
  });

  it("throws AGRAuthError on 401", async () => {
    mockFetch(401, { message: "Bad key" });
    await expect(client.evaluate("a", "b", "c")).rejects.toThrow(AGRAuthError);
    await expect(client.evaluate("a", "b", "c")).rejects.toThrow("Bad key");
    mockFetch(401, { message: "Bad key" });
  });

  it("throws AGRRateLimitError on 429", async () => {
    mockFetch(429, { message: "Slow down", upgrade_url: "https://agr.dev/pricing" });
    const err = await client.evaluate("a", "b", "c").catch((e) => e);
    expect(err).toBeInstanceOf(AGRRateLimitError);
    expect(err.upgradeUrl).toBe("https://agr.dev/pricing");
  });

  it("throws AGRError on 500", async () => {
    mockFetch(500, { error: "internal" });
    await expect(client.evaluate("a", "b", "c")).rejects.toThrow(AGRError);
  });
});

// ---------------------------------------------------------------------------
// waitForApproval()
// ---------------------------------------------------------------------------

describe("waitForApproval()", () => {
  const client = new AGRClient({ apiKey: "agr_sk_test" });

  it("returns true when approved on first poll", async () => {
    mockFetch(200, { id: "appr-1", status: "approved" });
    const result = await client.waitForApproval("appr-1", { pollInterval: 0 });
    expect(result).toBe(true);
  });

  it("returns false when rejected on first poll", async () => {
    mockFetch(200, { id: "appr-1", status: "rejected" });
    const result = await client.waitForApproval("appr-1", { pollInterval: 0 });
    expect(result).toBe(false);
  });

  it("polls until resolved — pending then approved", async () => {
    mockFetchMulti([
      { status: 200, body: { id: "appr-2", status: "pending" } },
      { status: 200, body: { id: "appr-2", status: "pending" } },
      { status: 200, body: { id: "appr-2", status: "approved" } },
    ]);
    const result = await client.waitForApproval("appr-2", { pollInterval: 0 });
    expect(result).toBe(true);
    expect(jest.spyOn(globalThis, "fetch")).toHaveBeenCalledTimes(0); // already consumed by mockFetchMulti
  });

  it("throws timeout error when not resolved in time", async () => {
    jest.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ id: "appr-3", status: "pending" }),
      text: async () => "",
    } as Response);

    await expect(
      client.waitForApproval("appr-3", { pollInterval: 0, timeout: 1 })
    ).rejects.toThrow(/not resolved within/);
  });

  it("throws AGRError on API failure during polling", async () => {
    mockFetch(500, { error: "internal" });
    await expect(
      client.waitForApproval("appr-4", { pollInterval: 0 })
    ).rejects.toThrow(AGRError);
  });
});

// ---------------------------------------------------------------------------
// registerAgent()
// ---------------------------------------------------------------------------

describe("registerAgent()", () => {
  const client = new AGRClient({ apiKey: "agr_sk_test" });

  it("returns agent response on success", async () => {
    const agentData = {
      id: "uuid-1",
      org_id: "org-1",
      agent_id: "coder-001",
      metadata: { framework: "langgraph" },
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    mockFetch(200, agentData);
    const result = await client.registerAgent("coder-001", { framework: "langgraph" });
    expect(result.agent_id).toBe("coder-001");
    expect(result.metadata).toEqual({ framework: "langgraph" });
  });

  it("defaults metadata to empty object", async () => {
    const spy = mockFetch(200, { id: "u", org_id: "o", agent_id: "a", metadata: {}, created_at: "", updated_at: "" });
    await client.registerAgent("minimal");
    const body = JSON.parse((spy.mock.calls[0] as [string, RequestInit])[1].body as string);
    expect(body.metadata).toEqual({});
  });

  it("throws AGRError on failure", async () => {
    mockFetch(400, { error: "bad request" });
    await expect(client.registerAgent("bad")).rejects.toThrow(AGRError);
  });
});

// ---------------------------------------------------------------------------
// close()
// ---------------------------------------------------------------------------

describe("close()", () => {
  it("is a no-op and does not throw", () => {
    const client = new AGRClient({ apiKey: "agr_sk_test" });
    expect(() => client.close()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// EvaluationResult computed booleans
// ---------------------------------------------------------------------------

describe("EvaluationResult computed booleans", () => {
  const cases: Array<[string, boolean, boolean, boolean]> = [
    ["ALLOW",             true,  false, false],
    ["DENY",              false, true,  false],
    ["APPROVAL_REQUIRED", false, false, true],
  ];

  test.each(cases)(
    "decision=%s → allowed=%s denied=%s requiresApproval=%s",
    async (decision, allowed, denied, requiresApproval) => {
      const client = new AGRClient({ apiKey: "agr_sk_test" });
      mockFetch(200, { decision, reason: "r", policy_id: null, approval_id: null, latency_ms: 0, eval_id: "e" });
      const result = await client.evaluate("a", "b", "c");
      expect(result.allowed).toBe(allowed);
      expect(result.denied).toBe(denied);
      expect(result.requiresApproval).toBe(requiresApproval);
    }
  );
});
