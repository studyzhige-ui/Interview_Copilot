'use strict';
/** Disposable real Docker integration only. Never point this at user data. */
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const { ComposeRuntime, projectName, command } = require('../runtime/compose.cjs');
async function main() {
  assert.equal(process.env.CI, 'true', 'Only a disposable CI host may run this campaign');
  assert.equal(process.env.IC_DESKTOP_ACCEPTANCE, '1');
  const resources = path.resolve(__dirname, '../.runtime');
  const manifest = JSON.parse(await fs.readFile(path.join(resources, 'desktop-runtime.json'), 'utf8'));
  assert.equal(manifest.auth.url, 'https://fixture.supabase.co');
  assert.equal(manifest.auth.publishableKey, 'sb_publishable_synthetic_fixture');
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'copilot-disposable-desktop-'));
  const redact = value => {
    for (const secret of Object.values(runtime.state || {}).filter(item => typeof item === 'string' && item.length >= 24)) value = value.replaceAll(secret, '[redacted]');
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
  const sql = async statement => runtime.run('docker', ['exec', await owned('db'), 'psql', '-U', 'postgres', '-d', 'interview_copilot', '-v', 'ON_ERROR_STOP=1', '-tAc', statement]);
  const object = async write => runtime.run('docker', ['exec', await owned('api'), 'python', '-c', `import boto3, os; s=boto3.client('s3',endpoint_url=os.environ['AWS_ENDPOINT_URL'],region_name='us-east-1'); bucket=os.environ['S3_BUCKET_NAME']; ${write ? "s.put_object(Bucket=bucket,Key='acceptance/synthetic.txt',Body=b'retained'); " : ''}assert s.get_object(Bucket=bucket,Key='acceptance/synthetic.txt')['Body'].read()==b'retained'`]);
  try {
    const first = await runtime.start();
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
    await sql("INSERT INTO users (id, username, hashed_password, is_active, email_verified, token_version, created_at, updated_at) VALUES (91001, 'desktop-acceptance-owner', 'synthetic-not-a-login', true, false, 3, now(), now())");
    await object(true);
    await fs.writeFile(path.join(root, 'data', 'synthetic-retention.txt'), 'retained');
    const settings = await fs.readFile(path.join(root, 'workspace.enc'));
    const candidate = (await runtime.run('docker', ['run', '-d', '--label', 'io.interview-copilot.acceptance=unrelated-sentinel', 'redis:8.10.0-alpine'])).trim();
    assert.match(candidate, /^[a-f0-9]{64}$/); sentinel = candidate;
    await runtime.stop();
    assert.equal(JSON.parse(await runtime.run('docker', ['inspect', sentinel]))[0].State.Running, true);
    report.checks.push('owned stop leaves unrelated container running');
    const second = await runtime.start(); assert.equal(first.origin, second.origin);
    assert.equal((await sql('SELECT token_version FROM users WHERE id=91001')).trim(), '3');
    await object(false);
    assert.equal(await fs.readFile(path.join(root, 'data', 'synthetic-retention.txt'), 'utf8'), 'retained');
    assert.deepEqual(await fs.readFile(path.join(root, 'workspace.enc')), settings);
    report.checks.push('restart retains owner, object, local file and original key settings');
    report.checks.push('ambient Postgres/MinIO credentials did not override workspace configuration');
    report.passed = true;
  } catch (error) {
    report.failure = error.message;
    if (runtime.state) for (const item of await runtime.inspectOwned(runtime.state).catch(() => [])) {
      const output = await runtime.run('docker', ['logs', '--tail', '35', item.Id]).catch(() => 'logs unavailable');
      let safe = output; for (const value of [runtime.state.secret, runtime.state.databasePassword, runtime.state.storageUser, runtime.state.storagePassword]) safe = safe.replaceAll(value, '[redacted]');
      console.error(item.Config.Labels['com.docker.compose.service'], safe);
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
