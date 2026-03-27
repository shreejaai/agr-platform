/**
 * Finance & Capital Markets — AGR domain scenario tests
 *
 * Runs all 15 FIN-* scenarios against a live AGR instance.
 * CI: runs on every PR against a test AGR instance.
 * Demo: run with --reporter=html for investor/leadership presentation.
 *
 * Requirements:
 *   AGR_API_KEY=agr_sk_...    (test org API key)
 *   AGR_BASE_URL=http://...   (defaults to localhost:8000)
 */

import { test, expect, request } from "@playwright/test";
import { AGRTestClient } from "./fixtures/agr-client";
import { seedDomain, teardownDomain, loadScenarios, Scenario } from "./fixtures/seed";
import type { PolicyResponse } from "./fixtures/agr-client";

let client: AGRTestClient;
let seededPolicies: PolicyResponse[] = [];
const scenarios: Scenario[] = loadScenarios("finance");

test.beforeAll(async () => {
  const ctx = await request.newContext();
  client = new AGRTestClient(ctx);

  const healthy = await client.healthCheck();
  if (!healthy) throw new Error("AGR instance is not healthy. Is it running?");

  seededPolicies = await seedDomain(client, "finance");
});

test.afterAll(async () => {
  await teardownDomain(client, seededPolicies);
});

// ── Scenario runner ──────────────────────────────────────────────────────────

for (const scenario of scenarios) {
  test(`[${scenario.id}] ${scenario.name}`, async () => {
    const response = await client.evaluate(scenario.request);

    // Primary assertion: decision must match expected
    expect(
      response.decision,
      `\nScenario: ${scenario.id} — ${scenario.name}\n` +
      `Narrative: ${scenario.narrative}\n` +
      `Expected: ${scenario.expected_decision}\n` +
      `Got:      ${response.decision}\n` +
      `Reason:   ${response.reason}\n` +
      `Risk:     ${response.risk_score} (${response.risk_level})\n` +
      `Engine:   ${response.decision_trace.policy_source}`
    ).toBe(scenario.expected_decision);

    // Risk level must match (HIGH scenarios should not score LOW)
    if (scenario.expected_risk_level === "HIGH") {
      expect(
        response.risk_score,
        `Risk score should be elevated for ${scenario.id}`
      ).toBeGreaterThan(30);
    }

    // Every response must include an eval_id (audit trail check)
    expect(response.eval_id).toBeTruthy();
    expect(response.latency_ms).toBeGreaterThan(0);

    // APPROVAL_REQUIRED must produce an approval_id
    if (scenario.expected_decision === "APPROVAL_REQUIRED") {
      expect(
        response.approval_id,
        `${scenario.id}: APPROVAL_REQUIRED must return an approval_id`
      ).toBeTruthy();
    }
  });
}

// ── Extra finance-specific assertions ───────────────────────────────────────

test("[FIN-02] OFAC block produces no approval_id — hard deny, no approval path", async () => {
  const ofacScenario = scenarios.find((s) => s.id === "FIN-02")!;
  const response = await client.evaluate(ofacScenario.request);
  expect(response.decision).toBe("DENY");
  expect(response.approval_id).toBeNull();
});

test("[FIN-04] Payroll batch under limit — latency under 200ms", async () => {
  const payroll = scenarios.find((s) => s.id === "FIN-04")!;
  const response = await client.evaluate(payroll.request);
  expect(response.decision).toBe("ALLOW");
  expect(response.latency_ms).toBeLessThan(200);
});

test("[FIN-13] Compliance officer read — no compliance findings", async () => {
  const complianceRead = scenarios.find((s) => s.id === "FIN-13")!;
  const response = await client.evaluate(complianceRead.request);
  expect(response.decision).toBe("ALLOW");
  const highFindings = response.compliance_findings.filter(
    (f) => f.severity === "high" || f.severity === "critical"
  );
  expect(highFindings).toHaveLength(0);
});
