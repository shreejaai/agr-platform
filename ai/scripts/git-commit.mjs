import { spawn } from 'child_process';

const message = process.argv.slice(2).join(' ') || process.env.AI_COMMIT_MESSAGE || 'chore(ai): apply autonomous changes';

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
  await run('git', ['add', '.']);
  await run('git', ['commit', '-m', message]);
  console.log(`Committed changes with message: ${message}`);
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
