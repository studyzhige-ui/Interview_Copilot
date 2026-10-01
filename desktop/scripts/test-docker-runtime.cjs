'use strict';
/** Disposable real Docker integration only. Never point this at user data. */
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const http = require('node:http');
const { ComposeRuntime, projectName, command, childEnvironment } = require('../runtime/compose.cjs');
async function main() {
  assert.equal(process.env.CI, 'true', 'Only a disposable CI host may run this campaign');
  assert.equal(process.env.IC_DESKTOP_ACCEPTANCE, '1');
  assert.equal(process.platform, 'linux', 'This campaign uses the disposable Linux Docker host');
  const resources = path.resolve(__dirname, '../.runtime');
  const manifest = JSON.parse(await fs.readFile(path.join(resources, 'desktop-runtime.json'), 'utf8'));
  assert.equal(manifest.auth.url, 'https://fixture.supabase.co');
  assert.equal(manifest.auth.publishableKey, 'sb_publishable_synthetic_fixture');
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'copilot-${HOME}-$UNSET-'));
  const privateValues = new Set();
  const redact = value => {
    for (const secret of Object.values(runtime.state || {}).filter(item => typeof item === 'string' && item.length >= 24)) value = value.replaceAll(secret, '[redacted]');
    for (const secret of privateValues) value = value.replaceAll(secret, '[redacted]');
    return value;
  };
  const runtime = new ComposeRuntime({ root, resources, bundle: manifest.bundle, auth: manifest.auth, encode: value => Buffer.from(value), decode: value => value.toString(), run: (executable, args, options) => command(executable, args, { ...options, onFailureDiagnostic: value => {
    const phase = args.includes('compose') ? `compose ${['version', 'config', 'up'].find(value => args.includes(value)) || 'other'}` : args[2];
    report.failure_stage ||= phase;
    console.error('Synthetic runtime diagnostic:', phase, redact(value));
  } }) });
  // Poison only this process. The production command boundary must drop these;
  // no contact with a remote daemon or external database is permitted.
  Object.assign(process.env, { DOCKER_HOST: 'ssh://must-not-be-used.invalid', DOCKER_CONTEXT: 'must-not-be-used', COMPOSE_FILE: '/must-not-be-used', POSTGRES_PASSWORD: 'ambient-not-workspace', AWS_ACCESS_KEY_ID: 'ambient-not-workspace', AWS_SECRET_ACCESS_KEY: 'ambient-not-workspace' });
  const report = { source_commit: process.env.IC_SOURCE_COMMIT || null, validation_only: true, platform: process.platform, passed: false, checks: [], boundary: 'Real disposable Linux Docker; no Windows/DPAPI/OS callbacks/live Auth/model inference' };
  const out = path.resolve(__dirname, '../runtime-acceptance.json');
  let sentinel;
  const owned = async name => (await runtime.inspectOwned(runtime.state)).find(item => item.Config.Labels['com.docker.compose.service'] === name).Id;
  const containerLogs = async id => {
    assert.match(id, /^[a-f0-9]{64}$/);
    try {
      const output = await promisify(execFile)('docker', ['--host', 'unix:///var/run/docker.sock', 'logs', id], { env: childEnvironment(), timeout: 15000, maxBuffer: 8 * 1024 * 1024 });
      return output.stdout + output.stderr;
    } catch { throw new Error('Cannot read complete disposable container logs'); }
  };
  const sql = async statement => runtime.run('docker', ['exec', await owned('db'), 'psql', '-U', 'postgres', '-d', 'interview_copilot', '-v', 'ON_ERROR_STOP=1', '-tAc', statement]);
  const request = (origin, route, token, options = {}) => fetch(origin + route, { ...options, redirect: 'error', signal: AbortSignal.timeout(15000), headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers } });
  const jsonRequest = (origin, route, token, method, body) => request(origin, route, token, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const unlock = async (origin, email) => {
    const response = await jsonRequest(origin, '/api/v1/auth/local-unlock', null, 'POST', { email, password: 'Synthetic-local-unlock-2026' });
    assert.equal(response.status, 200, 'Synthetic independent local unlock');
    const token = (await response.json()).access_token; assert.ok(token); privateValues.add(token); return token;
  };
  const rejectOversizedAtEdge = url => new Promise((resolve, reject) => {
    // Send only headers, never a 501 MiB body. nginx must reject immediately.
    const call = http.request(url, { method: 'PUT', headers: { 'Content-Length': String(501 * 1024 * 1024), 'Content-Type': 'text/plain' }, timeout: 5000 }, response => { response.resume(); response.on('end', () => resolve(response.statusCode)); });
    call.on('timeout', () => { call.destroy(); reject(new Error('Oversized edge request was not rejected promptly')); });
    call.on('error', () => reject(new Error('Oversized edge request failed before an HTTP response')));
    call.end();
  });
  try {
    const parent = path.join(root, '资料 with spaces $USER ${DATA}'); await fs.mkdir(parent);
    await runtime.selectDataDirectory(parent);
    const first = await runtime.start();
    assert.equal((await runtime.inspectOwned(runtime.state)).some(item => /minio/i.test(item.Config.Image)), false);
    report.checks.push('owned services and real database/Redis readiness');
    await runtime.run('docker', ['exec', await owned('api'), 'python', '-c', [
      'import time',
      'from app.task_queue.celery_app import celery_app',
      'deadline=time.monotonic()+60',
      "required={'turns','transcription','pipeline','jobs'}",
      'while True:',
      ' replies=celery_app.control.ping(timeout=2)',
      " names={name.split('@',1)[0] for reply in replies for name in reply}",
      ' if required <= names: break',
      " assert time.monotonic() < deadline, 'Owned Celery workers did not answer control ping'",
      ' time.sleep(1)',
    ].join('\n')], { timeout: 75000 });
    report.checks.push('all four real Celery worker lanes answer through the owned Redis broker');
    const config = await (await fetch(first.origin + '/api/v1/auth/config')).json();
    assert.equal(config.provider, 'supabase'); assert.equal(config.supabase_url, manifest.auth.url);
    assert.match(await (await fetch(first.origin)).text(), /id="root"/);
    report.checks.push('actual frontend and Auth configuration route');
    // Seed only synthetic, already-linked local profiles. Enrollment here is a
    // fixture; the real local-unlock endpoint below still verifies passwords.
    await runtime.run('docker', ['exec', await owned('api'), 'python', '-c', [
      'from app.db.database import SessionLocal',
      'from app.models.user import User',
      'from app.models.external_identity import ExternalIdentity',
      'from app.identity.application.local_unlock import enroll',
      'from app.identity.application.supabase_auth import issuer',
      'with SessionLocal() as db:',
      " for i, email in [(91001,'desktop-owner@example.com'),(91002,'desktop-other@example.com')]:",
      "  user=User(id=i,username=f'desktop-acceptance-{i}',email=email,hashed_password='synthetic-not-a-cloud-password',is_active=True,email_verified=True,token_version=3)",
      '  db.add(user);db.flush()',
      "  db.add(ExternalIdentity(user_id=i,issuer=issuer(),subject=f'00000000-0000-4000-8000-{i:012d}',email=email));db.commit()",
      "  enroll(db,user,'Synthetic-local-unlock-2026')",
    ].join('\n')]);
    let token = await unlock(first.origin, 'desktop-owner@example.com');
    const other = await unlock(first.origin, 'desktop-other@example.com');
    const original = Buffer.from('retained');
    const reserved = await jsonRequest(first.origin, '/api/v1/file-assets/upload-url', token, 'POST', { purpose: 'jd', filename: 'synthetic-retention.txt', content_type: 'text/plain', size_bytes: original.length });
    assert.equal(reserved.status, 200, 'Reserve owned file');
    const asset = await reserved.json(), upload = new URL(asset.upload_url, first.origin);
    assert.equal(upload.origin, first.origin); assert.ok((upload.searchParams.get('token') || '').length > 64); privateValues.add(upload.searchParams.get('token'));
    const uploaded = await fetch(upload, { method: 'PUT', redirect: 'error', headers: { 'Content-Type': 'text/plain' }, body: original });
    assert.equal(uploaded.status, 204, 'Bounded capability upload through real nginx');
    const confirmed = await jsonRequest(first.origin, `/api/v1/file-assets/${asset.file_asset_id}/confirm`, token, 'POST', {});
    assert.equal(confirmed.status, 200); assert.equal((await confirmed.json()).validation_status, 'passed');
    const replay = await fetch(upload, { method: 'PUT', headers: { 'Content-Type': 'text/plain' }, body: Buffer.from('tampered') });
    assert.equal(replay.status, 409, 'Confirmed bytes cannot be overwritten');
    const redirected = new URL(upload); redirected.pathname += '/';
    assert.equal((await fetch(redirected, { redirect: 'manual' })).status, 307);
    const rejected = new URL(upload); rejected.pathname += '/not-a-route';
    assert.equal((await fetch(rejected, { redirect: 'manual' })).status, 404);
    assert.equal(await rejectOversizedAtEdge(upload), 413, 'The 500 MiB edge cap remains enforced');
    const route = `/api/v1/file-assets/${asset.file_asset_id}/download`;
    const read = await request(first.origin, route, token); assert.equal(read.status, 200); assert.deepEqual(Buffer.from(await read.arrayBuffer()), original);
    assert.equal((await request(first.origin, route, other)).status, 404, 'Other account cannot read this file');
    const ranged = await request(first.origin, route, token, { headers: { Range: 'bytes=1-3' } });
    assert.equal(ranged.status, 206); assert.equal(ranged.headers.get('content-range'), 'bytes 1-3/8'); assert.equal(await ranged.text(), 'eta');
    const usage = await (await request(first.origin, '/api/v1/file-assets/storage-usage', token)).json();
    assert.equal(usage.backend, 'filesystem'); assert.equal(usage.used_bytes, 8); assert.equal(usage.asset_count, 1); assert.ok(usage.free_bytes > 0);
    assert.equal((await (await request(first.origin, '/api/v1/file-assets/storage-usage', other)).json()).used_bytes, 0);
    // A separate real Celery container must resolve the same file root/URI.
    await runtime.run('docker', ['exec', await owned('worker-jobs'), 'python', '-c', [
      'import sys', 'from app.db.database import SessionLocal', 'from app.models.file_asset import FileAsset', 'from app.core.storage import open_object',
      'with SessionLocal() as db:', ' asset=db.get(FileAsset,sys.argv[1])', " assert asset.storage_uri.startswith('local://')",
      " with open_object(asset.storage_uri) as stream: assert stream.read()==b'retained'",
    ].join('\n'), asset.file_asset_id]);
    report.checks.push('real local unlock, immutable upload/confirm, owner isolation, byte-range download and worker file resolution');
    await fs.writeFile(path.join(runtime.state.dataDirectory, 'synthetic-retention.txt'), 'retained');
    const settings = await fs.readFile(path.join(root, 'workspace.enc'));
    const candidate = (await runtime.run('docker', ['run', '-d', '--label', 'io.interview-copilot.acceptance=unrelated-sentinel', 'redis:8.10.0-alpine'])).trim();
    assert.match(candidate, /^[a-f0-9]{64}$/); sentinel = candidate;
    await runtime.stop();
    assert.equal(JSON.parse(await runtime.run('docker', ['inspect', sentinel]))[0].State.Running, true);
    report.checks.push('owned stop leaves unrelated container running');
    const second = await runtime.start(); assert.equal(first.origin, second.origin);
    assert.equal((await sql('SELECT token_version FROM users WHERE id=91001')).trim(), '3');
    token = await unlock(second.origin, 'desktop-owner@example.com');
    const retained = await request(second.origin, route, token); assert.equal(retained.status, 200); assert.deepEqual(Buffer.from(await retained.arrayBuffer()), original);
    assert.equal(await fs.readFile(path.join(runtime.state.dataDirectory, 'synthetic-retention.txt'), 'utf8'), 'retained');
    assert.deepEqual(await fs.readFile(path.join(root, 'workspace.enc')), settings);
    report.checks.push('restart retains owner, API-uploaded object, chosen literal-dollar path and original key settings');
    report.checks.push('ambient Postgres/S3 settings did not override filesystem configuration');
    for (const service of ['frontend', 'api']) {
      const logs = await containerLogs(await owned(service));
      for (const value of privateValues) assert.equal(logs.includes(value), false, 'Transfer/login capabilities must not enter access logs');
    }
    report.checks.push('edge/API stdout and stderr omit capabilities on success, redirect, rejected suffix and oversized-body rejection');
    report.passed = true;
  } catch (error) {
    report.failure = error.message;
    if (runtime.state) for (const item of await runtime.inspectOwned(runtime.state).catch(() => [])) {
      const output = await containerLogs(item.Id).catch(() => 'logs unavailable');
      console.error(item.Config.Labels['com.docker.compose.service'], redact(output));
    }
    throw error;
  } finally {
    await fs.writeFile(out, JSON.stringify(report, null, 2));
    // Remove only disposable fixtures created above, after verifying labels.
    if (runtime.state) {
      const items = await runtime.inspectOwned(runtime.state).catch(() => []);
      if (items.length) await runtime.run('docker', ['rm', '-f', ...items.map(item => item.Id)]).catch(() => {});
      const prefix = projectName(runtime.state.id) + '_';
      const volumes = (await runtime.run('docker', ['volume', 'ls', '--filter', `label=com.docker.compose.project=${projectName(runtime.state.id)}`, '--format', '{{.Name}}']).catch(() => '')).trim().split('\n').filter(Boolean);
      for (const volume of volumes) { assert.ok(volume.startsWith(prefix)); await runtime.run('docker', ['volume', 'rm', volume]).catch(() => {}); }
    }
    if (sentinel) await runtime.run('docker', ['rm', '-f', sentinel]).catch(() => {});
    await fs.rm(root, { recursive: true, force: true });
  }
  console.log(JSON.stringify(report, null, 2));
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
