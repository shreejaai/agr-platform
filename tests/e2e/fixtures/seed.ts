/**
 * Domain policy seeder for Playwright tests.
 * Loads policies.yaml for a given domain and creates them via the AGR API.
 * Call seedDomain() in beforeAll, teardownDomain() in afterAll.
 */

import * as fs from "fs";
import * as path from "path";
import * as yaml from "js-yaml";
import { AGRTestClient, PolicyResponse } from "./agr-client";

interface PolicyYaml {
  name: string;
  level: "org" | "agent" | "resource";
  cedar_rule: string;
  active: boolean;
  agent_id?: string;
}

interface PolicyPack {
  policies: PolicyYaml[];
}

const DOMAINS_DIR = path.resolve(__dirname, "../../../examples/domains");

export async function seedDomain(
  client: AGRTestClient,
  domain: "finance" | "pharma" | "banking" | "insurance"
): Promise<PolicyResponse[]> {
  const policiesPath = path.join(DOMAINS_DIR, domain, "policies.yaml");
  const raw = fs.readFileSync(policiesPath, "utf-8");
  const pack = yaml.load(raw) as PolicyPack;

  const created: PolicyResponse[] = [];

  for (const p of pack.policies) {
    const policy = await client.createPolicy({
      name: p.name,
      cedar_rule: p.cedar_rule,
      level: p.level ?? "org",
      state: p.active ? "active" : "draft",
      agent_id: p.agent_id,
    });
    created.push(policy);
  }

  console.log(`[seed] Created ${created.length} policies for domain: ${domain}`);
  return created;
}

export async function teardownDomain(
  client: AGRTestClient,
  policies: PolicyResponse[]
): Promise<void> {
  await Promise.all(policies.map((p) => client.deletePolicy(p.id)));
  console.log(`[seed] Deleted ${policies.length} domain policies`);
}

export function loadScenarios(
  domain: "finance" | "pharma" | "banking" | "insurance"
): Scenario[] {
  const scenariosPath = path.join(DOMAINS_DIR, domain, "scenarios.json");
  const raw = fs.readFileSync(scenariosPath, "utf-8");
  const data = JSON.parse(raw) as { scenarios: Scenario[] };
  return data.scenarios;
}

export interface Scenario {
  id: string;
  name: string;
  narrative: string;
  request: {
    agent_id: string;
    action: string;
    resource: string;
    context: Record<string, unknown>;
  };
  expected_decision: "ALLOW" | "DENY" | "APPROVAL_REQUIRED";
  expected_risk_level: "LOW" | "MEDIUM" | "HIGH";
  leadership_talking_point: string;
}
