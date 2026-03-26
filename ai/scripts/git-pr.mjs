import { spawn } from 'child_process';

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
  const title = process.env.AI_PR_TITLE || 'AI Generated Changes';
  const body = process.env.AI_PR_BODY || 'Automated changes from AI system';

  await run('git', ['push', 'origin', 'HEAD']);
  await run('gh', ['pr', 'create', '--title', title, '--body', body]);

  console.log('PR created successfully');
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
