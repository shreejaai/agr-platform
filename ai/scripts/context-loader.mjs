import fs from 'fs/promises';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const AI_ROOT = path.resolve(__dirname, '..');

export async function loadContext(task) {
  const configPath = path.join(AI_ROOT, 'config', 'context-map.json');
  const config = JSON.parse(await fs.readFile(configPath, 'utf-8'));

  const matchedGroups = new Set();

  for (const keyword of Object.keys(config.pathKeywords || {})) {
    if (task.toLowerCase().includes(keyword.toLowerCase())) {
      matchedGroups.add(config.pathKeywords[keyword]);
    }
  }

  if (matchedGroups.size === 0) {
    matchedGroups.add('api');
  }

  let context = '';

  for (const group of matchedGroups) {
    const paths = config.contextGroups[group] || [];

    for (const p of paths) {
      try {
        const fullPath = path.resolve(AI_ROOT, '..', p);
        const content = await fs.readFile(fullPath, 'utf-8');
        context += `\n--- FILE: ${p} ---\n${content.substring(0, 2000)}\n`;
      } catch {
        // skip missing files/directories for now
      }
    }
  }

  return context;
}