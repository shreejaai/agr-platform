/**
 * Insurance (P&C, Life, Health) — AGR domain scenario tests
 *
 * Runs all 10 INS-* scenarios.
 * Covers: NAIC model laws, HIPAA, state insurance codes, GDPR, ECOA, IFRS 17.
 */

import { test, expect, request } from "@playwright/test";
import { AGRTestClient } from "./fixtures/agr-client";
import { seedDomain, teardownDomain, loadScenarios, Scenario } from "./fixtures/seed";
import type { PolicyResponse } from "./fixtures/agr-client";

let client: AGRTestClient;
let seededPolicies: PolicyResponse[] = [];
const scenarios: Scenario[] = loadScenarios("insurance");

test.beforeAll(async () => {
  const ctx = await request.newContext();
  client = new AGRTestClient(ctx);

  const healthy = await client.healthCheck();
  if (!healthy) throw new Error("AGR instance is not healthy.");

  seededPolicies = await seedDomain(client, "insurance");
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
      `Risk:     ${response.risk_score} (${response.risk_level})\n` +
      `Engine:   ${response.decision_trace.policy_source}`
    ).toBe(scenario.expected_decision);

    expect(response.eval_id).toBeTruthy();
    expect(response.latency_ms).toBeGreaterThan(0);

    if (scenario.expected_decision === "APPROVAL_REQUIRED") {
      expect(
        response.approval_id,
        `${scenario.id}: APPROVAL_REQUIRED must return an approval_id`
      ).toBeTruthy();
    }

    if (scenario.expected_decision === "DENY") {
      expect(response.approval_id).toBeNull();
    }
  });
}

// ── Insurance-specific critical path assertions ──────────────────────────────

test("[INS-01] Small claim auto-approve — score threshold boundary (exactly $2500)", async () => {
  const scenario = scenarios.find((s) => s.id === "INS-01")!;

  // Exactly at limit — should allow
  const atLimit = {
    ...scenario.request,
    context: { ...scenario.request.context, claim_amount: 2500, fraud_score: 0.1 },
  };
  const allowResponse = await client.evaluate(atLimit);
  expect(allowResponse.decision).toBe("ALLOW");

  // One dollar over — should not auto-allow
  const overLimit = {
    ...scenario.request,
    context: { ...scenario.request.context, claim_amount: 2501, fraud_score: 0.1 },
  };
  const overResponse = await client.evaluate(overLimit);
  // No auto-approve policy matches — depends on default behavior
  expect(["DENY", "APPROVAL_REQUIRED"]).toContain(overResponse.decision);
});

test("[INS-02] Fraud score — score exactly 0.75 triggers SIU routing", async () => {
  const scenario = scenarios.find((s) => s.id === "INS-02")!;
  const boundary = {
    ...scenario.request,
    context: { ...scenario.request.context, fraud_score: 0.75 },
  };
  const response = await client.evaluate(boundary);
  expect(response.decision).toBe("APPROVAL_REQUIRED");
});

test("[INS-04] CA premium cap — other states not restricted at 25%+", async () => {
  const scenario = scenarios.find((s) => s.id === "INS-04")!;

  // Same increase in TX — should not be blocked by CA-specific rule
  const txPolicy = {
    ...scenario.request,
    context: { ...scenario.request.context, state: "TX", increase_pct: 30.0 },
  };
  const response = await client.evaluate(txPolicy);
  // TX is not in the CA rule — should not be denied by this policy
  expect(response.decision).not.toBe("DENY");
});

test("[INS-10] Protected class underwriting — ALLOW when no protected class used", async () => {
  const scenario = scenarios.find((s) => s.id === "INS-10")!;
  const clean = {
    ...scenario.request,
    context: {
      ...scenario.request.context,
      used_protected_class: false,
      protected_attributes_used: [],
    },
  };
  const response = await client.evaluate(clean);
  expect(response.decision).not.toBe("DENY");
});

test("[INS-06] Health record access — consent on file allows access", async () => {
  const scenario = scenarios.find((s) => s.id === "INS-06")!;
  const withConsent = {
    ...scenario.request,
    context: { ...scenario.request.context, consent_on_file: true },
  };
  const response = await client.evaluate(withConsent);
  expect(response.decision).not.toBe("DENY");
});
