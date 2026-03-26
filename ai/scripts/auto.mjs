import fs from 'fs/promises';
import { loadContext } from './context-loader.mjs';

const CLAUDE_API = 'https://api.anthropic.com/v1/messages';
const OLLAMA_API = 'http://localhost:11434/api/generate';

async function callClaude(prompt) {
  const res = await fetch(CLAUDE_API, {
    method: 'POST',
    headers: {
      'x-api-key': process.env.CLAUDE_API_KEY,
      'content-type': 'application/json'
    },
    body: JSON.stringify({
      model: 'claude-sonnet-4-5',
      max_tokens: 3000,
      messages: [{ role: 'user', content: prompt }]
    })
  });
  const data = await res.json();
  return data.content?.[0]?.text || '';
}

async function callOllama(prompt) {
  const res = await fetch(OLLAMA_API, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: 'qwen:latest', prompt })
  });
  const data = await res.json();
  return data.response || '';
}

function isPass(review) {
  return review.includes('OVERALL VERDICT: PASS');
}

async function run(task) {
  console.log('Loading context...');
  const context = await loadContext(task);

  const planner = await fs.readFile('ai/prompts/planner-advanced.md', 'utf-8');
  const reviewer = await fs.readFile('ai/prompts/reviewer-structured.md', 'utf-8');

  console.log('Planning...');
  let plan = await callClaude(`${context}\n\n${planner}\n\nTask:\n${task}`);

  let iteration = 0;
  let output = '';
  let review = '';

  while (iteration < 5) {
    console.log(`Iteration ${iteration + 1}`);

    console.log('Executing...');
    output = await callOllama(plan);

    console.log('Reviewing...');
    review = await callClaude(`${reviewer}\n\n${output}`);

    if (isPass(review)) {
      console.log('PASS achieved');
      break;
    }

    console.log('Fixing...');
    plan = review;
    iteration++;
  }

  await fs.writeFile('ai/tmp/final.txt', output);
  console.log('Final output saved to ai/tmp/final.txt');
}

const task = process.argv.slice(2).join(' ');
run(task);
