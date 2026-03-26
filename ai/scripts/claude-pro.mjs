import fs from "fs/promises";
import { loadContext } from "./context-loader.mjs";

async function ensureTmp() {
  await fs.mkdir("ai/tmp", { recursive: true });
}

async function preparePlan(task) {
  const context = await loadContext(task);
  const planner = await fs.readFile("ai/prompts/planner-advanced.md", "utf-8");

  const prompt = `${context}

${planner}

Task:
${task}`;

  await fs.writeFile("ai/tmp/plan_prompt.txt", prompt);
  console.log("✅ plan_prompt.txt ready → paste into Claude");
}

async function prepareReview() {
  const reviewer = await fs.readFile("ai/prompts/reviewer-structured.md", "utf-8");
  const output = await fs.readFile("ai/tmp/output.txt", "utf-8");

  const prompt = `${reviewer}

Code:
${output}`;

  await fs.writeFile("ai/tmp/review_prompt.txt", prompt);
  console.log("✅ review_prompt.txt ready → paste into Claude");
}

async function prepareFix() {
  const review = await fs.readFile("ai/tmp/review.txt", "utf-8");

  const prompt = `Fix the code based on:

${review}

Return only updated code.`;

  await fs.writeFile("ai/tmp/fix_prompt.txt", prompt);
  console.log("✅ fix_prompt.txt ready → run in Qwen");
}

const cmd = process.argv[2];
const arg = process.argv.slice(3).join(" ");

await ensureTmp();

if (cmd === "plan") await preparePlan(arg);
else if (cmd === "review") await prepareReview();
else if (cmd === "fix") await prepareFix();
else console.log("Use: plan | review | fix");