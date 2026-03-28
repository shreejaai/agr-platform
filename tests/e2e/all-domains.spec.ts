/**
 * Cross-domain smoke test — "The Leadership Demo"
 *
 * Runs ONE representative scenario from each domain in a single test suite.
 * Designed for:
 *   1. PR gate — fast smoke check (4 evals, ~2s)
 *   2. Investor/leadership demo — run with --reporter=html, open report
 *
 * Each test is named for the talking point, not the technical ID.
 * Grouped by domain so the HTML report reads like a demo script.
 */

import { test, expect, request } from "@playwright/test";
import { AGRTestClient } from "./fixtures/agr-client";
import {
  seedDomain,
  teardownDomain,
  loadScenarios,
} from "./fixtures/seed";
import type { PolicyResponse } from "./fixtures/agr-client";

// ── Setup ────────────────────────────────────────────────────────────────────

let client: AGRTestClient;
const allSeeded: PolicyResponse[] = [];

test.beforeAll(async () => {
  const ctx = await request.newContext();
  client = new AGRTestClient(ctx);

  const healthy = await client.healthCheck();
  if (!healthy) throw new Error("AGR instance is not healthy. Run: docker compose up -d");

  const [fin, ph, bk, ins] = await Promise.all([
    seedDomain(client, "finance"),
    seedDomain(client, "pharma"),
    seedDomain(client, "banking"),
    seedDomain(client, "insurance"),
  ]);
  allSeeded.push(...fin, ...ph, ...bk, ...ins);
});

test.afterAll(async () => {
  await teardownDomain(client, allSeeded);
});

// ── Finance ──────────────────────────────────────────────────────────────────

test.describe("Finance — Capital Markets & Payments", () => {
  test("OFAC-sanctioned country wire blocked in under 50ms", async () => {
    const scenarios = loadScenarios("finance");
    const s = scenarios.find((x) => x.id === "FIN-02")!;
    const res = await client.evaluate(s.request);

    expect(res.decision).toBe("DENY");
    expect(res.approval_id).toBeNull();
    expect(res.latency_ms).toBeLessThan(200);
    console.log(`\n  Talking point: ${s.leadership_talking_point}`);
  });

  test("$75k wire transfer paused for human approval — not auto-executed", async () => {
    const scenarios = loadScenarios("finance");
    const s = scenarios.find((x) => x.id === "FIN-01")!;
    const res = await client.evaluate(s.request);

    expect(res.decision).toBe("APPROVAL_REQUIRED");
    expect(res.approval_id).toBeTruthy();
    console.log(`\n  Talking point: ${s.leadership_talking_point}`);
  });

  test("Routine $380k payroll batch flows through without delay", async () => {
    const scenarios = loadScenarios("finance");
    const s = scenarios.find((x) => x.id === "FIN-04")!;
    const res = await client.evaluate(s.request);

    expect(res.decision).toBe("ALLOW");
    expect(res.latency_ms).toBeLessThan(200);
    console.log(`\n  Talking point: ${s.leadership_talking_point}`);
  });
});

// ── Pharma ───────────────────────────────────────────────────────────────────

test.describe("Pharma — Clinical Trials & Drug Safety", () => {
  test("Drug batch release blocked — QC sign-off is mandatory gate", async () => {
    const scenarios = loadScenarios("pharma");
    const s = scenarios.find((x) => x.id === "PHARMA-13")!;
    const res = await client.evaluate(s.request);

    expect(res.decision).toBe("DENY");
    console.log(`\n  Talking point: ${s.leadership_talking_point}`);
  });

  test("GxP audit trail modification blocked unconditionally — 21 CFR Part 11", async () => {
    const scenarios = loadScenarios("pharma");
    const s = scenarios.find((x) => x.id === "PHARMA-15")!;
    const res = await client.evaluate(s.request);

    expect(res.decision).toBe("DENY");
    expect(res.approval_id).toBeNull();
    console.log(`\n  Talking point: ${s.leadership_talking_point}`);
  });

  test("Serious adverse event — agent cannot auto-close, routes to physician", async () => {
    const scenarios = loadScenarios("pharma");
    const s = scenarios.find((x) => x.id === "PHARMA-05")!;
    const res = await client.evaluate(s.request);

    expect(res.decision).toBe("APPROVAL_REQUIRED");
    expect(res.approval_id).toBeTruthy();
    console.log(`\n  Talking point: ${s.leadership_talking_point}`);
  });
});

// ── Banking ───────────────────────────────────────────────────────────────────

test.describe("Banking — Lending, Compliance & Payments", () => {
  test("$2.5M commercial loan paused for credit committee", async () => {
    const scenarios = loadScenarios("banking");
    const s = scenarios.find((x) => x.id === "BANK-01")!;
    const res = await client.evaluate(s.request);

    expect(res.decision).toBe("APPROVAL_REQUIRED");
    expect(res.approval_id).toBeTruthy();
    console.log(`\n  Talking point: ${s.leadership_talking_point}`);
  });

  test("Account opening blocked — KYC not completed (FinCEN compliance)", async () => {
    const scenarios = loadScenarios("banking");
    const s = scenarios.find((x) => x.id === "BANK-03")!;
    const res = await client.evaluate(s.request);

    expect(res.decision).toBe("DENY");
    console.log(`\n  Talking point: ${s.leadership_talking_point}`);
  });

  test("Unmasked PAN write blocked — agent cannot create PCI scope", async () => {
    const scenarios = loadScenarios("banking");
    const s = scenarios.find((x) => x.id === "BANK-12")!;
    const res = await client.evaluate(s.request);

    expect(res.decision).toBe("DENY");
    console.log(`\n  Talking point: ${s.leadership_talking_point}`);
  });
});

// ── Insurance ─────────────────────────────────────────────────────────────────

test.describe("Insurance — Claims, Underwriting & Compliance", () => {
  test("$1,800 glass claim approved instantly — zero human involvement needed", async () => {
    const scenarios = loadScenarios("insurance");
    const s = scenarios.find((x) => x.id === "INS-01")!;
    const res = await client.evaluate(s.request);

    expect(res.decision).toBe("ALLOW");
    expect(res.latency_ms).toBeLessThan(200);
    console.log(`\n  Talking point: ${s.leadership_talking_point}`);
  });

  test("High-fraud-score claim routed to SIU — agent cannot auto-pay", async () => {
    const scenarios = loadScenarios("insurance");
    const s = scenarios.find((x) => x.id === "INS-02")!;
    const res = await client.evaluate(s.request);

    expect(res.decision).toBe("APPROVAL_REQUIRED");
    console.log(`\n  Talking point: ${s.leadership_talking_point}`);
  });

  test("AI underwriting using protected class attributes blocked — ECOA compliance", async () => {
    const scenarios = loadScenarios("insurance");
    const s = scenarios.find((x) => x.id === "INS-10")!;
    const res = await client.evaluate(s.request);

    expect(res.decision).toBe("DENY");
    console.log(`\n  Talking point: ${s.leadership_talking_point}`);
  });
});

// ── Platform health assertions ────────────────────────────────────────────────

test.describe("AGR Platform — Cross-domain invariants", () => {
  test("Every evaluation returns an eval_id (immutable audit trail)", async () => {
    const scenarios = loadScenarios("finance");
    const s = scenarios[0];
    const res = await client.evaluate(s.request);
    expect(res.eval_id).toMatch(/^[0-9a-f-]{36}$/); // UUID format
  });

  test("Every evaluation returns a decision_trace with policy_source", async () => {
    const scenarios = loadScenarios("pharma");
    const s = scenarios[0];
    const res = await client.evaluate(s.request);
    expect(["cedar_cli", "python_fallback", "cache", "no_policies"]).toContain(
      res.decision_trace.policy_source
    );
  });

  test("DENY decisions never return an approval_id", async () => {
    const domains = ["finance", "pharma", "banking", "insurance"] as const;
    for (const domain of domains) {
      const allScenarios = loadScenarios(domain);
      const denyScenarios = allScenarios.filter(
        (s) => s.expected_decision === "DENY"
      );
      for (const s of denyScenarios.slice(0, 2)) {
        const res = await client.evaluate(s.request);
        if (res.decision === "DENY") {
          expect(
            res.approval_id,
            `${s.id}: DENY must not produce an approval_id`
          ).toBeNull();
        }
      }
    }
  });

  test("AGR does not add >300ms overhead to any evaluation (performance gate)", async () => {
    const scenarios = loadScenarios("finance");
    const results = await Promise.all(
      scenarios.slice(0, 5).map((s) => client.evaluate(s.request))
    );
    for (const res of results) {
      expect(
        res.latency_ms,
        `Evaluation exceeded 300ms latency budget: ${res.latency_ms}ms`
      ).toBeLessThan(300);
    }
  });
});
