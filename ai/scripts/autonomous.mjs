import { loadContext } from './context-loader.mjs';
import fs from 'fs/promises';

export async function runAutonomous(task) {
  console.log('Context-aware execution starting');

  const context = await loadContext(task);

  await fs.writeFile('ai/tmp/context.txt', context);

  console.log('Context loaded and saved');

  // Next steps handled via CLI flow
  console.log('Run: ai:plan → ai:execute → ai:review → ai:fix');
}
