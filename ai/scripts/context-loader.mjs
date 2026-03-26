import fs from 'fs/promises';
import path from 'path';

export async function loadContext(task) {
  const config = JSON.parse(await fs.readFile('ai/config/context-map.json', 'utf-8'));

  const matchedGroups = new Set();

  for (const keyword of Object.keys(config.pathKeywords)) {
    if (task.toLowerCase().includes(keyword)) {
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
        const fullPath = path.resolve(p);
        const content = await fs.readFile(fullPath, 'utf-8');
        context += `\n--- FILE: ${p} ---\n${content.substring(0, 2000)}\n`;
      } catch (e) {
        // skip missing
      }
    }
  }

  return context;
}
