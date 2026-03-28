/**
 * Playwright configuration for AGR domain e2e tests.
 *
 * Three named projects:
 *   smoke       — all-domains.spec.ts only (fast, runs on every PR)
 *   full-suite  — all spec files (runs nightly + pre-release)
 *   demo        — all-domains.spec.ts with HTML reporter (leadership presentation)
 *
 * Usage:
 *   npx playwright test --project=smoke          # PR gate
 *   npx playwright test --project=full-suite     # full validation
 *   npx playwright test --project=demo           # investor demo
 *   npx playwright show-report                   # open HTML report after demo run
 */

import { defineConfig, devices } from "@playwright/test";
import * as dotenv from "dotenv";
import * as path from "path";

// Load .env.test if it exists (local dev). CI sets env vars directly.
dotenv.config({ path: path.resolve(__dirname, ".env.test") });

const AGR_BASE_URL = process.env["AGR_BASE_URL"] ?? "http://localhost:8000";

export default defineConfig({
  testDir: "./",

  // Hard timeout per test — AGR evaluations should be fast
  timeout: 15_000,

  // Global setup timeout (policy seeding across 4 domains)
  globalTimeout: 300_000,

  // Retry once on flake in CI, no retries locally
  retries: process.env["CI"] ? 1 : 0,

  // Parallelise across spec files, but run tests within a file serially
  // (beforeAll/afterAll manage policy state per file)
  fullyParallel: false,
  workers: 4,

  // Default reporter — overridden per project below
  reporter: [
    ["list"],
    ["json", { outputFile: "test-results/results.json" }],
  ],

  use: {
    baseURL: AGR_BASE_URL,
    // All tests are API-only — no browser needed
    // extraHTTPHeaders set per test via AGRTestClient
    trace: "retain-on-failure",
  },

  projects: [
    // ── Smoke: PR gate ───────────────────────────────────────────────────────
    {
      name: "smoke",
      testMatch: "**/all-domains.spec.ts",
      use: { ...devices["Desktop Chrome"] },
    },

    // ── Full suite: nightly + pre-release ────────────────────────────────────
    {
      name: "full-suite",
      testMatch: "**/*.spec.ts",
      use: { ...devices["Desktop Chrome"] },
    },

    // ── Demo: investor / leadership presentation ──────────────────────────────
    {
      name: "demo",
      testMatch: "**/all-domains.spec.ts",
      reporter: [
        [
          "html",
          {
            outputFolder: "test-results/demo-report",
            open: "always",
          },
        ],
      ],
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
