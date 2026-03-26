import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';
import { loadContext } from './context-loader.mjs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const AI_ROOT = path.resolve(__dirname, '..');

async function ensureTmp() {
  await fs.mkdir(path.join(AI_ROOT, 'tmp'), { recursive: true });
}

async function preparePlan(task) {
  const context = await loadContext(task);
  const planner = await fs.readFile(path.join(AI_ROOT, 'prompts', 'planner-advanced.md'), 'utf-8');
  const prompt = `${context}\n\n${planner}\n\nTask:\n${task}`;
  await fs.writeFile(path.join(AI_ROOT, 'tmp', 'plan_prompt.txt'), prompt, 'utf-8');
  console.log('plan_prompt.txt ready');
}

async function prepareReview() {
  const reviewer = await fs.readFile(path.join(AI_ROOT, 'prompts', 'reviewer-structured.md'), 'utf-8');
  const output = await fs.readFile(path.join(AI_ROOT, 'tmp', 'output.txt'), 'utf-8');
  const prompt = `${reviewer}\n\nImplementation:\n${output}`;
  await fs.writeFile(path.join(AI_ROOT, 'tmp', 'review_prompt.txt'), prompt, 'utf-8');
  console.log('review_prompt.txt ready');
}

async function prepareFix() {
  const review = await fs.readFile(path.join(AI_ROOT, 'tmp', 'review.txt'), 'utf-8');
  const prompt = `Apply the following review feedback with minimal necessary changes.\nPreserve unrelated logic.\nReturn code or patch only.\n\n${review}`;
  await fs.writeFile(path.join(AI_ROOT, 'tmp', 'fix_prompt.txt'), prompt, 'utf-8');
  console.log('fix_prompt.txt ready');
}

const cmd = process.argv[2];
const arg = process.argv.slice(3).join(' ');

await ensureTmp();

if (cmd === 'plan') {
  if (!arg) throw new Error('Provide a task');
  await preparePlan(arg);
} else if (cmd === 'review') {
  await prepareReview();
} else if (cmd === 'fix') {
  await prepareFix();
} else {
  console.log('Use: plan | review | fix');
}
