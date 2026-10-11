'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { CallbackGate, parseCallback } = require('../auth-callback.cjs');
const { createDataDirectory, verifyDataDirectory, discardUncommittedDataDirectory } = require('../runtime/data-directory.cjs');
const { safePath, webURL } = require('../policy.cjs');

test('native account callbacks must match one live intent and cannot replay', () => {
  let pending = null, now = 100;
  const gate = new CallbackGate({ read: () => pending, write: value => { pending = value; }, now: () => now });
  const begin = gate.begin('signup');
  const url = `interview-copilot://auth/confirm?code=abcdefghijklmnop#state=${begin.id}`;
  assert.equal(gate.consume(url).id, begin.id);
  assert.equal(gate.consume(url), null);
  const second = gate.begin('recovery');
  now += 11 * 60 * 1000;
  assert.equal(gate.consume(`interview-copilot://auth/recovery?code=abcdefghijklmnop#state=${second.id}`), null);
});

test('privileged origins, traversal and callback tokens are rejected', () => {
  for (const url of ['javascript:alert(1)', 'file:///C:/secret', 'https://user:pass@example.org']) assert.throws(() => webURL(url));
  assert.throws(() => safePath(path.resolve('safe'), '../outside'));
  assert.equal(parseCallback('interview-copilot://auth/confirm?access_token=secret'), null);
});

test('workspace creation preserves existing data and checks the installation owner', async t => {
  const parent = await fs.mkdtemp(path.join(os.tmpdir(), 'copilot-contract-'));
  // Only this test-owned temporary directory is removed.
  t.after(() => fs.rm(parent, { recursive: true }));
  const id = 'a'.repeat(24);
  const directory = await createDataDirectory(parent, id, parent);
  assert.equal(await verifyDataDirectory(directory, id), directory);
  await assert.rejects(verifyDataDirectory(directory, 'b'.repeat(24)));
  await assert.rejects(createDataDirectory(parent, id, parent));
  await fs.writeFile(path.join(directory, 'recording.wav'), 'user data');
  assert.equal(await discardUncommittedDataDirectory(directory, id), false);
  assert.equal(await fs.readFile(path.join(directory, 'recording.wav'), 'utf8'), 'user data');
});

test('desktop package has exactly the production entrypoint', async () => {
  const pkg = JSON.parse(await fs.readFile(path.join(__dirname, '../package.json'), 'utf8'));
  assert.equal(pkg.main, 'main.cjs');
  assert.equal(pkg.scripts.prototype, undefined);
  const main = await fs.readFile(path.join(__dirname, '../main.cjs'), 'utf8');
  assert(!main.includes('prototype-main'));
});
