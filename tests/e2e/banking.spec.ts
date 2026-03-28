/**
 * Retail & Corporate Banking — AGR domain scenario tests
 *
 * Runs all 12 BANK-* scenarios.
 * Covers: Basel III, BSA/AML, KYC (FinCEN), ECOA, FDIC, PCI-DSS, GDPR.
 */

import { test, expect, request } from "@playwright/test";
import { AGRTestClient } from "./fixtures/agr-client";
import { seedDomain, teardownDomain, loadScenarios, Scenario } from "./fixtures/seed";
import type { PolicyResponse } from "./fixtures/agr-client";

let client: AGRTestClient;
let seededPolicies: PolicyResponse[] = [];
const scenarios: Scenario[] = loadScenarios("banking");

test.beforeAll(async () => {
  const ctx = await request.newContext();
  client = new AGRTestClient(ctx);

  const healthy = await client.healthCheck();
  if (!healthy) throw new Error("AGR instance is not healthy.");

  seededPolicies = await seedDomain(client, "banking");
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

// ── Banking-specific critical path assertions ────────────────────────────────

test("[BANK-02] Fraud-flagged customer — hard deny regardless of amount", async () => {
  // Small loan amount should not bypass fraud flag
  const scenario = scenarios.find((s) => s.id === "BANK-02")!;
  const smallLoan = {
    ...scenario.request,
    context: { ...scenario.request.context, principal_amount: 1000 },
  };
  const response = await client.evaluate(smallLoan);
  expect(response.decision).toBe("DENY");
});

test("[BANK-11] Overdraft protection — opt-in required, amount gated", async () => {
  const scenario = scenarios.find((s) => s.id === "BANK-11")!;

  // Opt-out should not allow
  const optOut = {
    ...scenario.request,
    context: { ...scenario.request.context, opt_in: false },
  };
  const denyResponse = await client.evaluate(optOut);
  expect(denyResponse.decision).not.toBe("ALLOW");

  // Over limit should not allow
  const overLimit = {
    ...scenario.request,
    context: { ...scenario.request.context, overdraft_amount: 1500, opt_in: true },
  };
  const limitResponse = await client.evaluate(overLimit);
  expect(limitResponse.decision).not.toBe("ALLOW");
});

test("[BANK-12] PCI card data — tokenized write is permitted", async () => {
  const scenario = scenarios.find((s) => s.id === "BANK-12")!;
  const tokenized = {
    ...scenario.request,
    context: { ...scenario.request.context, tokenized: true, pan_present: false },
  };
  const response = await client.evaluate(tokenized);
  // Tokenized write should not be blocked by the PCI policy
  expect(response.decision).not.toBe("DENY");
});

test("[BANK-07] Mortgage DTI — exactly 43% is permitted (boundary condition)", async () => {
  const scenario = scenarios.find((s) => s.id === "BANK-07")!;
  const boundary = {
    ...scenario.request,
    context: {
      ...scenario.request.context,
      dti_ratio: 0.43,
      fraud_flag: false,
      principal_amount: 350000,
    },
  };
  const response = await client.evaluate(boundary);
  // At exactly 43% the forbid condition (> 0.43) does not trigger
  expect(response.decision).not.toBe("DENY");
});

test("[BANK-03] Account opening — completed KYC is allowed", async () => {
  const scenario = scenarios.find((s) => s.id === "BANK-03")!;
  const kycDone = {
    ...scenario.request,
    context: { ...scenario.request.context, kyc_status: "completed" },
  };
  const response = await client.evaluate(kycDone);
  expect(response.decision).not.toBe("DENY");
});
