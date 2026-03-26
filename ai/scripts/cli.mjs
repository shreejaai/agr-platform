import fs from 'fs/promises';

const CLAUDE_API = 'https://api.anthropic.com/v1/messages';
const OLLAMA_API = 'http://localhost:11434/api/generate';

const CLAUDE_KEY = process.env.CLAUDE_API_KEY;

async function readFile(path) {
  return fs.readFile(path, 'utf-8');
}

async function callClaude(prompt) {
  const res = await fetch(CLAUDE_API, {
    method: 'POST',
    headers: {
      'x-api-key': CLAUDE_KEY,
      'content-type': 'application/json'
    },
    body: JSON.stringify({
      model: 'claude-3-opus-20240229',
      max_tokens: 2000,
      messages: [{ role: 'user', content: prompt }]
    })
  });
  const data = await res.json();
  return data.content?.[0]?.text || JSON.stringify(data);
}

async function callOllama(prompt) {
  const res = await fetch(OLLAMA_API, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: 'qwen:latest', prompt })
  });
  const data = await res.json();
  return data.response;
}

async function main() {
  const cmd = process.argv[2];

  if (cmd === 'plan') {
    const task = process.argv.slice(3).join(' ');
    const planner = await readFile('/prompts/planner-advanced.md');
    const output = await callClaude(`${planner}\n\nTask:\n${task}`);
    console.log(output);
  }

  if (cmd === 'execute') {
    const input = await readFile('/tmp/plan.txt');
    const output = await callOllama(input);
    console.log(output);
  }

  if (cmd === 'review') {
    const code = await readFile('/tmp/output.txt');
    const reviewer = await readFile('/prompts/reviewer.md');
    const output = await callClaude(`${reviewer}\n\n${code}`);
    console.log(output);
  }

  if (cmd === 'fix') {
    const review = await readFile('/tmp/review.txt');
    const output = await callOllama(review);
    console.log(output);
  }
}

main();
