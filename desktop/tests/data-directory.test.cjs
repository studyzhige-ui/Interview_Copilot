'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const { createDataDirectory, selectedParent, verifyDataDirectory, discardUncommittedDataDirectory } = require('../runtime/data-directory.cjs');
const { ComposeRuntime, writeSettingsExclusively } = require('../runtime/compose.cjs');
const installation = 'a'.repeat(24);
const auth = { provider: 'supabase', url: 'https://fixture.supabase.co', publishableKey: 'sb_publishable_synthetic_fixture' };
const state = { id: installation, bundle: 'b'.repeat(64), port: 21781, storagePort: 21782, secret: 'c'.repeat(64), databasePassword: 'd'.repeat(64), storageUser: 'e'.repeat(24), storagePassword: 'f'.repeat(64) };
async function fixture(t) {
  const root = await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), 'copilot-directory-test-')));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  return root;
}
test('chosen directory gets an exclusive owned child while unrelated files remain untouched', async t => {
  const root = await fixture(t), parent = path.join(root, '资料 with spaces $USER ${HOME}');
  await fs.mkdir(parent); await fs.writeFile(path.join(parent, 'original.txt'), 'original');
  const directory = await createDataDirectory(root, installation, parent);
  assert.equal(directory, path.join(parent, 'Interview Copilot', installation));
  assert.equal(await verifyDataDirectory(directory, installation), directory);
  assert.equal(await fs.readFile(path.join(parent, 'original.txt'), 'utf8'), 'original');
  await assert.rejects(createDataDirectory(root, installation, parent), /已存在/);
  await assert.rejects(verifyDataDirectory(directory, 'b'.repeat(24)), /另一工作区/);
});
test('existing default directories and redirected selected/owned directories are never adopted', async t => {
  const root = await fixture(t), data = path.join(root, 'data'), foreign = path.join(root, 'foreign');
  await fs.mkdir(data); await fs.mkdir(foreign); await fs.writeFile(path.join(data, 'original.txt'), 'original');
  await assert.rejects(createDataDirectory(root, installation), /已存在/);
  const link = path.join(root, 'link'); await fs.symlink(foreign, link, 'junction');
  await assert.rejects(selectedParent(link), /链接/);
  await fs.mkdir(path.join(root, 'choice')); await fs.symlink(foreign, path.join(root, 'choice', 'Interview Copilot'), 'junction');
  await assert.rejects(createDataDirectory(root, installation, path.join(root, 'choice')), /链接/);
  assert.equal(await fs.readFile(path.join(data, 'original.txt'), 'utf8'), 'original');
});
test('persisted custom directory remains fixed and original protected settings are not rewritten', async t => {
  const root = await fixture(t), parent = path.join(root, 'chosen'); await fs.mkdir(parent);
  const directory = await createDataDirectory(root, installation, parent);
  const settings = Buffer.from(JSON.stringify({ ...state, dataDirectory: directory }));
  await fs.writeFile(path.join(root, 'workspace.enc'), settings);
  const runtime = new ComposeRuntime({ root, resources: root, bundle: state.bundle, auth, encode: value => Buffer.from(value), decode: value => value.toString() });
  assert.deepEqual(await runtime.dataDirectoryInfo(), { canChooseDirectory: false, dataDirectory: directory, dataDirectoryIsParent: false });
  await assert.rejects(runtime.selectDataDirectory(root), /不能直接更换/);
  assert.equal((await runtime.load()).secret, state.secret);
  assert.deepEqual(await fs.readFile(path.join(root, 'workspace.enc')), settings);
});
test('legacy settings retain their original location and corrupt settings cannot enable directory selection', async t => {
  const root = await fixture(t);
  const runtime = new ComposeRuntime({ root, resources: root, bundle: state.bundle, auth, encode: value => Buffer.from(value), decode: value => value.toString() });
  await fs.writeFile(path.join(root, 'workspace.enc'), JSON.stringify(state));
  assert.equal((await runtime.dataDirectoryInfo()).dataDirectory, path.join(root, 'data'));
  await fs.writeFile(path.join(root, 'workspace.enc'), 'corrupt');
  await assert.rejects(runtime.dataDirectoryInfo(), /不会修改/);
  await assert.rejects(runtime.selectDataDirectory(root), /不会修改/);
  assert.equal(await fs.readFile(path.join(root, 'workspace.enc'), 'utf8'), 'corrupt');
});
test('failed first settings persistence can retry without adopting an orphan or caching unsaved keys', async t => {
  const root = await fixture(t); let nextPort = 24000, failWrite = true;
  t.mock.method(net, 'createServer', () => { const server = { once: () => server, listen: (_port, _host, callback) => callback(), address: () => ({ port: nextPort++ }), close: callback => callback() }; return server; });
  const open = fs.open.bind(fs);
  t.mock.method(fs, 'open', async (location, ...args) => {
    const handle = await open(location, ...args);
    if (failWrite && location.startsWith(path.join(root, 'workspace.enc.'))) {
      failWrite = false;
      return { writeFile: async data => { await handle.writeFile(data.subarray(0, 5)); const error = new Error('synthetic disk full after partial write'); error.code = 'ENOSPC'; throw error; }, sync: handle.sync.bind(handle), close: handle.close.bind(handle) };
    }
    return handle;
  });
  const runtime = new ComposeRuntime({ root, resources: root, bundle: state.bundle, auth, encode: value => Buffer.from(value), decode: value => value.toString() });
  await assert.rejects(runtime.load(), { code: 'ENOSPC' });
  assert.equal(runtime.state, null);
  await assert.rejects(fs.stat(path.join(root, 'data')), { code: 'ENOENT' });
  assert.deepEqual(await fs.readdir(root), []);
  const created = await runtime.load();
  assert.equal(await verifyDataDirectory(created.dataDirectory, created.id), created.dataDirectory);
  assert.equal(JSON.parse(await fs.readFile(path.join(root, 'workspace.enc'), 'utf8')).secret, created.secret);
});
test('atomic settings publication refuses to replace an existing key file', async t => {
  const root = await fixture(t), location = path.join(root, 'workspace.enc');
  await fs.writeFile(location, 'original-protected-settings');
  await assert.rejects(writeSettingsExclusively(location, Buffer.from('replacement')), { code: 'EEXIST' });
  assert.equal(await fs.readFile(location, 'utf8'), 'original-protected-settings');
  assert.deepEqual(await fs.readdir(root), ['workspace.enc']);
});
test('a partial first ownership-marker write leaves no corrupt final marker and retries safely', async t => {
  const root = await fixture(t); let failWrite = true;
  const open = fs.open.bind(fs);
  t.mock.method(fs, 'open', async (location, ...args) => {
    const handle = await open(location, ...args);
    if (failWrite && path.basename(location).startsWith('.copilot-data-owner.json.')) {
      failWrite = false;
      return { writeFile: async data => { await handle.writeFile(data.slice(0, 4)); const error = new Error('partial marker write'); error.code = 'ENOSPC'; throw error; }, sync: handle.sync.bind(handle), close: handle.close.bind(handle) };
    }
    return handle;
  });
  await assert.rejects(createDataDirectory(root, installation), { code: 'ENOSPC' });
  assert.deepEqual(await fs.readdir(root), []);
  const directory = await createDataDirectory(root, installation);
  assert.equal(await verifyDataDirectory(directory, installation), directory);
});
test('failure cleanup preserves original files and rejects another installation marker', async t => {
  const root = await fixture(t), directory = await createDataDirectory(root, installation);
  assert.equal(await discardUncommittedDataDirectory(directory, 'b'.repeat(24)), false);
  await fs.writeFile(path.join(directory, 'original.txt'), 'retained');
  assert.equal(await discardUncommittedDataDirectory(directory, installation), false);
  assert.equal(await fs.readFile(path.join(directory, 'original.txt'), 'utf8'), 'retained');
  assert.equal(await verifyDataDirectory(directory, installation), directory);
});

test('canonical spelling changes require the same filesystem directory identity', async t => {
  const root = await fixture(t), requested = path.join(root, 'short-spelling'), canonical = path.join(root, 'long-spelling');
  await fs.mkdir(requested); await fs.mkdir(canonical);
  const lstat = fs.lstat.bind(fs), realpath = fs.realpath.bind(fs), identity = await lstat(requested, { bigint: true });
  t.mock.method(fs, 'realpath', location => location === requested ? Promise.resolve(canonical) : realpath(location));
  t.mock.method(fs, 'lstat', (location, ...args) => location === canonical ? Promise.resolve(identity) : lstat(location, ...args));
  assert.equal(await selectedParent(requested), canonical);
  t.mock.restoreAll();
  t.mock.method(fs, 'realpath', location => location === requested ? Promise.resolve(canonical) : realpath(location));
  await assert.rejects(selectedParent(requested), /重定向/);
});
test('a directory below a redirected ancestor is refused even when its leaf is ordinary', async t => {
  const root = await fixture(t), actual = path.join(root, 'actual'), redirected = path.join(root, 'redirected');
  await fs.mkdir(actual); await fs.mkdir(path.join(actual, 'child')); await fs.symlink(actual, redirected, 'junction');
  await assert.rejects(selectedParent(path.join(redirected, 'child')), /链接/);
});
test('the operating system temp spelling resolves to the verified canonical directory', async t => {
  const requested = await fs.mkdtemp(path.join(os.tmpdir(), 'copilot-alias-test-'));
  t.after(() => fs.rm(requested, { recursive: true, force: true }));
  const canonical = await fs.realpath(requested);
  t.diagnostic(JSON.stringify({ platform: process.platform, requested, canonical, spellingChanged: path.relative(requested, canonical) !== '' }));
  assert.equal(await selectedParent(requested), canonical);
  const directory = await createDataDirectory(requested, installation);
  assert.equal(directory, path.join(canonical, 'data'));
  assert.equal(await verifyDataDirectory(path.join(requested, 'data'), installation), directory);
});
