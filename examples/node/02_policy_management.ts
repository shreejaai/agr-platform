/**
 * Policy management demo — create, list, import, export via the AGR API.
 *
 * Usage:
 *   AGR_API_KEY=agr_sk_... npx ts-node 02_policy_management.ts
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

async function apiFetch(path: string, init?: RequestInit) {
  const resp = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: { ...headers, ...(init?.headers ?? {}) },
  });
  return resp.json();
}

const policiesToImport = [
  {
    name: "TS Demo: Allow staging",
    level: "org",
    cedar_rule:
      'permit(principal, action == Action::"deploy", resource) when { context has environment && context.environment == "staging" };',
  },
  {
    name: "TS Demo: Deny prod drops",
    level: "org",
    cedar_rule:
      'forbid(principal, action == Action::"db.drop", resource) when { context has environment && context.environment == "production" };',
  },
];

(async () => {
  // 1. Dry-run import
  console.log("1. Dry-run import...");
  const dryRun = await apiFetch("/v1/policies/import", {
    method: "POST",
    body: JSON.stringify({ policies: policiesToImport, dry_run: true }),
  });
  console.log(`   Would create: ${dryRun.created}, errors: ${dryRun.errors}`);

  // 2. Real import
  console.log("2. Real import (overwrite)...");
  const imported = await apiFetch("/v1/policies/import", {
    method: "POST",
    body: JSON.stringify({ policies: policiesToImport, overwrite: true }),
  });
  console.log(`   Created: ${imported.created}, Updated: ${imported.updated}`);

  // 3. List policies
  console.log("3. All policies:");
  const list = await apiFetch("/v1/policies");
  for (const p of list) {
    console.log(`   [${p.active ? "active" : "inactive"}] ${p.name}`);
  }

  // 4. Export
  console.log("4. Export:");
  const exported = await apiFetch("/v1/policies/export");
  console.log(`   Total exported: ${exported.total}`);
})();
