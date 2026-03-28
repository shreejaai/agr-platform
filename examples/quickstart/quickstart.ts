import { AGRClient } from "../../packages/agr-sdk-ts/src/client.js";

async function main(): Promise<void> {
  const client = new AGRClient({
    apiKey: process.env["AGR_API_KEY"],
    baseUrl: process.env["AGR_BASE_URL"] ?? "http://localhost:8000",
  });

  const agent = await client.registerAgent("example-agent", { framework: "quickstart" });
  console.log("Registered agent:", agent.agent_id);

  const allowResult = await client.evaluate(
    "example-agent",
    "read_docs",
    "getting-started",
    { environment: "development", risk_level: "low" },
  );
  console.log("Low-risk decision:", allowResult.decision, "-", allowResult.reason);

  const approvalResult = await client.evaluate(
    "example-agent",
    "deploy",
    "checkout-service",
    { environment: "production" },
  );
  console.log("Sensitive decision:", approvalResult.decision, "-", approvalResult.reason);

  if (approvalResult.approvalId) {
    try {
      const approved = await client.waitForApproval(approvalResult.approvalId, { timeout: 5000 });
      console.log("Approval resolved:", approved ? "approved" : "rejected");
    } catch (error) {
      console.log("Approval still pending after 5 seconds. Exiting gracefully.");
    }
  }
}

void main();
