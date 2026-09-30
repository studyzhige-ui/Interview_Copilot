'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { ownedModel, publicConfig, environment, validateState, ComposeRuntime, REQUIRED, LABEL } = require('../runtime/compose.cjs');
const state = { id: 'a'.repeat(24), bundle: 'b'.repeat(64), port: 21781, storagePort: 21782, secret: 'synthetic_'.repeat(8), databasePassword: 'c'.repeat(64), storageUser: 'd'.repeat(24), storagePassword: 'e'.repeat(64) };
const auth = publicConfig({ provider: 'supabase', url: 'https://fixture.supabase.co', publishableKey: 'sb_publishable_synthetic_fixture' });
test('owned runtime retains all business lanes while making infrastructure private', () => {
  const model = { services: Object.fromEntries([...REQUIRED, 'migrate'].map(name => [name, { container_name: 'preexisting-fixed-name', image: 'shared-image', build: { context: '/release' }, ports: [{ published: '80', host_ip: '0.0.0.0', target: 80 }], volumes: [{ type: 'bind', source: '/release/data', target: '/app/data' }] }])) };
  const result = ownedModel(model, state, 'C:/Users/fixture/我的工作区/data');
  assert.deepEqual(Object.keys(result.services).sort(), [...REQUIRED, 'migrate'].sort());
  for (const [name, service] of Object.entries(result.services)) {
    assert.equal(service.container_name, undefined); assert.equal(service.labels[LABEL], state.id);
    assert.equal(service.volumes[0].source, 'C:/Users/fixture/我的工作区/data');
    if (!['frontend', 'minio'].includes(name)) assert.equal(service.ports, undefined);
    else assert.equal(service.ports[0].host_ip, '127.0.0.1');
    assert.ok(service.image.startsWith(`interview-copilot-${state.id}-`));
  }
});
test('release Auth configuration accepts only public keys and HTTPS project origin', () => {
  for (const config of [{ ...auth, publishableKey: 'sb_secret_fixture' }, { ...auth, url: 'http://fixture.supabase.co' }, { ...auth, url: 'https://fixture.supabase.co/path' }, { ...auth, url: 'https://user:pass@fixture.supabase.co' }, { ...auth, provider: 'local' }]) assert.throws(() => publicConfig(config));
  const env = environment(state, auth); assert.ok(env.includes('AUTH_PROVIDER=supabase')); assert.ok(env.includes(`SECRET_KEY=${state.secret}`));
  assert.ok(!env.includes('minioadmin')); assert.throws(() => environment({ ...state, secret: 'value\nINJECTED=yes' }, auth));
});
test('corrupt local state fails instead of silently rotating data encryption keys', () => {
  assert.equal(validateState(state), state);
  for (const edit of [{ secret: null }, { port: '21781' }, { storagePort: state.port }, { id: '../foreign' }, { bundle: 'changed' }]) assert.throws(() => validateState({ ...state, ...edit }));
});
test('foreign container ownership rejects before any mutating command', async () => {
  const calls = [];
  const runtime = new ComposeRuntime({ root: '/unused', resources: '/unused', bundle: state.bundle, auth, run: async (_exe, args) => { calls.push(args); return args[2] === 'ps' ? JSON.stringify({ ID: 'a'.repeat(12) }) : JSON.stringify([{ Config: { Labels: { [LABEL]: 'other-installation' } } }]); } });
  await assert.rejects(runtime.inspectOwned(state), /标识冲突/);
  assert.deepEqual(calls.map(args => args[2]), ['ps', 'inspect']);
});
test('stop is scoped to the owned project and never removes containers or data volumes', async () => {
  const calls = [];
  const runtime = new ComposeRuntime({ root: '/unused', resources: '/unused', bundle: state.bundle, auth, run: async (_exe, args) => { calls.push(args); return ''; } });
  runtime.check = async () => {}; runtime.load = async options => { assert.deepEqual(options, { create: false, allowBundleMismatch: true }); return state; };
  runtime.inspectOwned = async () => [{ Id: 'a'.repeat(64) }];
  assert.deepEqual(await runtime.stop(), { stopped: true, dataRetained: true });
  assert.deepEqual(calls, [['--host', 'unix:///var/run/docker.sock', 'stop', '--time', '30', 'a'.repeat(64)]]);
});
test('Windows container mode is rejected and no start is attempted', async () => {
  const calls = [];
  const runtime = new ComposeRuntime({ root: '/unused', resources: '/unused', bundle: state.bundle, auth, run: async (_exe, args) => { calls.push(args); return JSON.stringify({ OSType: 'windows' }); } });
  await assert.rejects(runtime.start(), /Linux 容器/);
  assert.equal(calls.length, 1); assert.equal(runtime.busy, false);
});

const { childEnvironment } = require('../runtime/compose.cjs');
test('ambient remote Docker and interpolation settings never reach child processes', () => {
  const result = childEnvironment({ PATH: '/fixture/bin', SystemRoot: 'C:/Windows', DOCKER_HOST: 'ssh://foreign', DOCKER_CONTEXT: 'remote', COMPOSE_FILE: '/foreign.yml', POSTGRES_PASSWORD: 'ambient', AWS_ACCESS_KEY_ID: 'ambient', SECRET_KEY: 'ambient', NODE_OPTIONS: '--require=foreign' });
  assert.deepEqual(result, { PATH: '/fixture/bin', SystemRoot: 'C:/Windows', DOCKER_CLI_HINTS: 'false' });
});
test('Windows checks always pin the official local named pipe irrespective of selected context', async () => {
  const calls = [];
  const runtime = new ComposeRuntime({ root: '/unused', resources: '/unused', bundle: state.bundle, auth, platform: 'win32', run: async (_exe, args) => { calls.push(args); return args.includes('info') ? JSON.stringify({ OSType: 'linux', OperatingSystem: 'Docker Desktop' }) : '2.40.0'; } });
  await runtime.check();
  assert.ok(calls.every(args => args[0] === '--host' && args[1] === 'npipe:////./pipe/docker_engine'));
});
