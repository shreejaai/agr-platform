/**
 * Basic evaluate demo using the AGR TypeScript SDK.
 *
 * Usage:
 *   npm install agr-sdk  (or: pnpm add agr-sdk)
 *   AGR_API_KEY=agr_sk_... npx ts-node 01_basic_evaluate.ts
 */

const BASE_URL = process.env.AGR_BASE_URL ?? "http://localhost:8000";
const API_KEY = process.env.AGR_API_KEY ?? "";

if (!API_KEY) {
  console.error("ERROR: Set AGR_API_KEY environment variable");
  process.exit(1);
}

const headers = {
  Authorization: `Bearer ${API_KEY}`,
  "Content-Type": "application/json",
};

interface EvaluateRequest {
  agent_id: string;
  action: string;
  resource: string;
  context?: Record<string, unknown>;
  approver_email?: string;
}

interface EvaluateResponse {
  decision: string;
  reason: string;
  policy_id: string | null;
  approval_id: string | null;
  latency_ms: number;
  eval_id: string;
  risk_score: number | null;
  risk_level: string | null;
  compliance_findings: Array<{
    plugin: string;
    standard: string;
    rule_id: string;
    severity: string;
    message: string;
    passed: boolean;
  }> | null;
}

async function evaluate(req: EvaluateRequest): Promise<EvaluateResponse> {
  const resp = await fetch(`${BASE_URL}/v1/evaluate`, {
    method: "POST",
    headers,
    body: JSON.stringify(req),
  });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
  }
  return resp.json() as Promise<EvaluateResponse>;
}

const testCases: Array<{ label: string; req: EvaluateRequest }> = [
  {
    label: "Low-risk read (expect ALLOW)",
    req: { agent_id: "trusted-reader", action: "read", resource: "docs.txt" },
  },
  {
    label: "Production db.drop (expect DENY)",
    req: {
      agent_id: "coder-001",
      action: "db.drop",
      resource: "prod-db",
      context: { environment: "production" },
    },
  },
  {
    label: "Large bulk delete (risk engine may upgrade)",
    req: {
      agent_id: "agent-9999",
      action: "delete",
      resource: "user-table",
      context: { count: 500000, environment: "production" },
    },
  },
];

(async () => {
  for (const { label, req } of testCases) {
    const result = await evaluate(req);
    const risk = result.risk_level ?? "n/a";
    console.log(`[${result.decision.padEnd(20)}] risk=${risk.padEnd(6)} ${label}`);
  }
})();
