import fs from 'fs/promises';

const OLLAMA_API = 'http://localhost:11434/api/generate';

async function callOllama(prompt) {
  const res = await fetch(OLLAMA_API, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: 'qwen:latest', prompt })
  });
  const data = await res.json();
  return data.response || '';
}

async function run() {
  const code = await fs.readFile('ai/tmp/final.txt', 'utf-8');

  const prompt = `Generate unit tests for the following code. Focus on edge cases and production scenarios:\n\n${code}`;

  const tests = await callOllama(prompt);

  await fs.writeFile('ai/tmp/tests.txt', tests);

  console.log('Tests generated at ai/tmp/tests.txt');
}

run();
