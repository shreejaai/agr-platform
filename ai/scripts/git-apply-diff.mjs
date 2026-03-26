import fs from 'fs/promises';
import { spawn } from 'child_process';

const PATCH_FILE = process.env.AI_PATCH_FILE || 'ai/tmp/generated.patch';

function run(cmd, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: 'inherit' });
    child.on('close', (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${cmd} exited with code ${code}`));
    });
  });
}

async function main() {
  const patch = await fs.readFile(PATCH_FILE, 'utf-8');
  if (!patch.trim()) {
    throw new Error(`Patch file ${PATCH_FILE} is empty`);
  }

  console.log(`Applying patch from ${PATCH_FILE}`);
  await run('git', ['apply', '--whitespace=fix', PATCH_FILE]);
  console.log('Patch applied successfully');
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
