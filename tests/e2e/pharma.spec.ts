/**
 * Pharmaceutical & Life Sciences — AGR domain scenario tests
 *
 * Runs all 15 PHARMA-* scenarios.
 * Covers: GCP, 21 CFR Part 11, HIPAA, ICH E6, EU CTR, GxP.
 */

import { test, expect, request } from "@playwright/test";
import { AGRTestClient } from "./fixtures/agr-client";
import { seedDomain, teardownDomain, loadScenarios, Scenario } from "./fixtures/seed";
import type { PolicyResponse } from "./fixtures/agr-client";

let client: AGRTestClient;
let seededPolicies: PolicyResponse[] = [];
const scenarios: Scenario[] = loadScenarios("pharma");

test.beforeAll(async () => {
  const ctx = await request.newContext();
  client = new AGRTestClient(ctx);

  const healthy = await client.healthCheck();
  if (!healthy) throw new Error("AGR instance is not healthy.");

  seededPolicies = await seedDomain(client, "pharma");
});

test.afterAll(async () => {
  await teardownDomain(client, seededPolicies);
});

// ── Scenario runner ──────────────────────────────────────────────────────────

for (const scenario of scenarios) {
  test(`[${scenario.id}] ${scenario.name}`, async () => {
    const response = await client.evaluate(scenario.request);

    expect(
      response.decision,
      `\nScenario: ${scenario.id} — ${scenario.name}\n` +
      `Narrative: ${scenario.narrative}\n` +
      `Expected: ${scenario.expected_decision}\n` +
      `Got:      ${response.decision}\n` +
      `Reason:   ${response.reason}\n` +
      `Engine:   ${response.decision_trace.policy_source}`
    ).toBe(scenario.expected_decision);

    expect(response.eval_id).toBeTruthy();

    if (scenario.expected_decision === "APPROVAL_REQUIRED") {
      expect(response.approval_id).toBeTruthy();
    }

    if (scenario.expected_decision === "DENY") {
      expect(response.approval_id).toBeNull();
    }
  });
}

// ── Pharma-specific critical path assertions ─────────────────────────────────

test("[PHARMA-15] 21 CFR Part 11 — audit trail modification is unconditional DENY", async () => {
  // Even with approval_status=approved injected, this should still DENY
  const scenario = scenarios.find((s) => s.id === "PHARMA-15")!;
  const withApproval = {
    ...scenario.request,
    context: { ...scenario.request.context, approval_status: "approved" },
  };
  const response = await client.evaluate(withApproval);
  expect(response.decision).toBe("DENY");
});

test("[PHARMA-08] NDA submission — decision trace shows policy matched, not risk override", async () => {
  const scenario = scenarios.find((s) => s.id === "PHARMA-08")!;
  const response = await client.evaluate(scenario.request);
  expect(response.decision).toBe("DENY");
  expect(response.decision_trace.matched_policy_id).toBeTruthy();
  expect(response.decision_trace.risk_override).toBe(false);
});

test("[PHARMA-13] Batch release — QC approved flag allows release", async () => {
  const scenario = scenarios.find((s) => s.id === "PHARMA-13")!;
  const approved = {
    ...scenario.request,
    context: { ...scenario.request.context, qc_approved: true },
  };
  const response = await client.evaluate(approved);
  // With QC approved, policy should permit
  expect(["ALLOW", "APPROVAL_REQUIRED"]).toContain(response.decision);
});
