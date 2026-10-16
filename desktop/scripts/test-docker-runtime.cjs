'use strict';
// Disposable end-to-end runtime: real Compose, health, stop and restart.
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const { ComposeRuntime, command, projectName, LABEL } = require('../runtime/compose.cjs');

async function main() {
  if (process.platform !== 'linux' || process.env.IC_DESKTOP_ACCEPTANCE !== '1') throw new Error('Requires explicit Linux acceptance environment');
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'copilot-runtime-contract-'));
  const resources = path.resolve(__dirname, '../.runtime');
  const manifest = JSON.parse(await fs.readFile(path.join(resources, 'desktop-runtime.json'), 'utf8'));
  const runtime = new ComposeRuntime({root, resources, bundle: manifest.bundle,
    auth: manifest.auth,
    encode: value => Buffer.from(value), decode: value => value.toString(),
    run: (executable, args, options) => command(executable, args, {...options,
      onFailureDiagnostic: diagnostic => {
        // Only this disposable fixture may expose CLI diagnostics. Never emit
        // interpolated workspace credentials, even when Docker prints config.
        for (const key of ['secret', 'databasePassword', 'storageUser', 'storagePassword']) {
          if (runtime.state?.[key]) diagnostic = diagnostic.replaceAll(runtime.state[key], '[REDACTED]');
        }
        console.error(diagnostic);
      },
    })});
  let completed = false;
  try {
    const first = await runtime.start();
    const identity = {...runtime.state};
    const sentinel = path.join(identity.dataDirectory, 'contract-sentinel');
    await fs.writeFile(sentinel, 'retained');
    assert.equal((await runtime.stop()).dataRetained, true);
    assert.equal((await runtime.start()).origin, first.origin);
    assert.equal(await fs.readFile(sentinel, 'utf8'), 'retained');
    assert.deepEqual(runtime.state, identity);
    completed = true;
  } finally {
    if (runtime.state) {
      await runtime.stop();
      const owned = await runtime.inspectOwned(runtime.state);
      if (!owned.every(item => item.Config.Labels[LABEL] === runtime.state.id)) throw new Error('Cleanup ownership mismatch');
      if (owned.length) await command('docker', ['rm', ...owned.map(item => item.Id)]);
      const project = projectName(runtime.state.id);
      for (const type of ['volume', 'network']) {
        const names = (await command('docker', [type, 'ls', '--filter', `label=com.docker.compose.project=${project}`, '--format', '{{.Name}}'])).trim().split('\n').filter(Boolean);
        if (names.length) await command('docker', [type, 'rm', ...names]);
      }
    }
    if (!root.startsWith(path.join(os.tmpdir(), 'copilot-runtime-contract-'))) throw new Error('Cleanup path mismatch');
    await fs.rm(root, {recursive: true, force: true});
    await fs.writeFile(path.resolve(__dirname, '../runtime-acceptance.json'), JSON.stringify({completed, checks: ['health', 'identity-retained', 'data-retained', 'restart']}, null, 2));
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
