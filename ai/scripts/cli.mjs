import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const AI_ROOT = path.resolve(__dirname, '..');

async function readFile(filePath) {
  return fs.readFile(filePath, 'utf-8');
}

async function callOllama(prompt) {
  const res = await fetch('http://localhost:11434/api/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: 'qwen3.5:latest',
      prompt,
      stream: false
    })
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Ollama request failed: ${res.status} ${text}`);
  }

  const data = await res.json();
  return data.response || '';
}

async function main() {
  const cmd = process.argv[2];

  if (cmd === 'execute') {
    const input = await readFile(path.join(AI_ROOT, 'tmp', 'plan.txt'));
    const output = await callOllama(input);

    await fs.writeFile(path.join(AI_ROOT, 'tmp', 'output.txt'), output, 'utf-8');
    console.log(output);
    return;
  }

  if (cmd === 'fix') {
    const review = await readFile(path.join(AI_ROOT, 'tmp', 'review.txt'));
    const output = await callOllama(review);

    await fs.writeFile(path.join(AI_ROOT, 'tmp', 'final.txt'), output, 'utf-8');
    console.log(output);
    return;
  }

  console.log('Use: execute | fix');
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});