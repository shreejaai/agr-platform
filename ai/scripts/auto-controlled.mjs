import fs from 'fs/promises';
import { loadContext } from './context-loader.mjs';

const OLLAMA_API = 'http://localhost:11434/api/generate';
const MAX_ITERATIONS = Number(process.env.AI_MAX_LOOPS || 5);
const STOP_FILE = process.env.AI_STOP_FILE || 'ai/tmp/STOP';

// async function callClaude(prompt) {
//   const res = await fetch(CLAUDE_API, {
//     method: 'POST',
//     headers: {
//       'x-api-key': process.env.CLAUDE_API_KEY,
//       'content-type': 'application/json'
//     },
//     body: JSON.stringify({
//       model: 'claude-sonnet-4-5',
//       max_tokens: 3000,
//       messages: [{ role: 'user', content: prompt }]
//     })
//   });
//   const data = await res.json();
//   return data.content?.[0]?.text || '';
// }

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

async function shouldStopFromFile() {
  try {
    await fs.access(STOP_FILE);
    return true;
  } catch {
    return false;
  }
}

async function run(task) {
  console.log('Loading context...');
  const context = await loadContext(task);
  const planner = await fs.readFile('/prompts/planner-advanced.md', 'utf-8');
  const reviewer = await fs.readFile('/prompts/reviewer-structured.md', 'utf-8');

  console.log('Planning...');
  let plan = await callClaude(`${context}\n\n${planner}\n\nTask:\n${task}`);

  let iteration = 0;
  let output = '';
  let previousOutput = '';

  while (iteration < MAX_ITERATIONS) {
    if (await shouldStopFromFile()) {
      console.log(`Stop file detected at ${STOP_FILE}. Breaking loop.`);
      break;
    }

    console.log(`Iteration ${iteration + 1} of ${MAX_ITERATIONS}`);

    output = await callOllama(plan);

    if (output === previousOutput && output.length > 0) {
      console.log('Output unchanged from previous iteration. Stopping loop.');
      break;
    }

    previousOutput = output;

    const review = await callClaude(`${reviewer}\n\n${output}`);
    await fs.writeFile('/tmp/review.txt', review);

    if (isPass(review)) {
      console.log('PASS achieved. Stopping loop.');
      break;
    }

    plan = review;
    iteration += 1;
  }

  await fs.writeFile('/tmp/final.txt', output);
  console.log('Final output saved to ai/tmp/final.txt');
}

const task = process.argv.slice(2).join(' ');
run(task);
