'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { prepareRuntime } = require('../scripts/prepare-runtime.cjs');

test('installed runtime includes every local Docker COPY source and excludes private configuration', t => {
  const target = fs.mkdtempSync(path.join(os.tmpdir(), 'copilot-bundle-contract-'));
  t.after(() => fs.rmSync(target, { recursive: true, force: true }));
  const manifest = prepareRuntime({
    root: path.resolve(__dirname, '../..'), target,
    auth: { provider: 'supabase', url: 'https://fixture.supabase.co', publishableKey: 'sb_publishable_synthetic_fixture' },
  });
  for (const dockerfile of ['backend/Dockerfile', 'frontend/Dockerfile', 'infra/postgres/Dockerfile']) {
    const source = fs.readFileSync(path.join(target, dockerfile), 'utf8').replace(/\\\r?\n/g, ' ');
    for (const line of source.split(/\r?\n/)) {
      if (!/^COPY\s/i.test(line) || /--from=/.test(line)) continue;
      const tokens = line.trim().split(/\s+/).slice(1).filter(token => !token.startsWith('--'));
      for (const name of tokens.slice(0, -1)) {
        assert(fs.existsSync(path.join(target, name)), `${dockerfile} requires missing runtime source ${name}`);
      }
    }
  }
  assert(manifest.files.some(file => file.path === '.dockerignore'));
  assert(!manifest.files.some(file => file.path.split('/').some(name => name.startsWith('.env') || name === 'node_modules' || name === '.git')));
});
