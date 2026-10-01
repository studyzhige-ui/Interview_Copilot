'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..'), release = path.join(root, 'release');
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
async function main() {
  const asar = await import('@electron/asar');
  const archive = path.join(release, 'win-unpacked/resources/app.asar');
  const packaged = asar.listPackage(archive).map(name => name.replaceAll('\\', '/'));
  const required = ['main.cjs', 'runtime/compose.cjs', 'runtime/data-directory.cjs', 'runtime/private-file.cjs', 'permissions.cjs', 'auth-callback.cjs', 'product-preload.cjs', 'runtime-preload.cjs', 'setup/index.html'];
  for (const name of required) {
    assert.ok(packaged.includes('/' + name), `Missing packaged ${name}`);
    assert.equal(hash(asar.extractFile(archive, name)), hash(fs.readFileSync(path.join(root, name))), `Stale packaged ${name}`);
  }
  const resources = path.join(release, 'win-unpacked/resources/runtime');
  const manifest = JSON.parse(fs.readFileSync(path.join(resources, 'desktop-runtime.json'), 'utf8'));
  assert.equal(manifest.auth.provider, 'supabase');
  assert.ok(manifest.auth.publishableKey.startsWith('sb_publishable_'));
  assert.equal(new URL(manifest.auth.url).protocol, 'https:');
  const requiredSources = ['docker-compose.yml', 'pyproject.toml', 'backend/Dockerfile', 'backend/docker-entrypoint.sh', 'backend/app/main.py', 'frontend/Dockerfile', 'frontend/package-lock.json', 'frontend/src/main.tsx', 'infra/postgres/Dockerfile', 'nginx/conf.d/frontend.conf', 'alembic/env.py'];
  for (const name of requiredSources) assert.ok(manifest.files.some(item => item.path === name), `Missing runtime source ${name}`);
  for (const item of manifest.files) {
    assert.ok(!path.isAbsolute(item.path) && !item.path.split('/').includes('..'));
    assert.ok(!item.path.split('/').some(part => part.startsWith('.env') || ['node_modules', '.git', '__pycache__'].includes(part)), `Forbidden runtime input ${item.path}`);
    assert.equal(hash(fs.readFileSync(path.join(resources, item.path))), item.sha256, `Runtime integrity ${item.path}`);
  }
  assert.equal(hash(JSON.stringify(manifest.files)), manifest.bundle);
  let installer = null;
  if (process.argv.includes('--installer')) {
    const file = path.join(release, 'Interview-Copilot-acceptance-fixture.exe');
    const bytes = fs.readFileSync(file); assert.ok(bytes.length > 5 * 1024 * 1024, 'Incomplete installer'); assert.equal(bytes.subarray(0, 2).toString(), 'MZ');
    installer = { filename: path.basename(file), bytes: bytes.length, sha256: hash(bytes) };
  }
  const report = { validation_only: true, source_commit: process.env.IC_SOURCE_COMMIT || null, runtime_bundle: manifest.bundle, runtime_files: manifest.files.length, packaged_sources_match: true, installer, boundaries: ['No Windows installation or Docker Desktop lifecycle is asserted', 'Synthetic public Auth configuration; no live signup/email/password', 'No code signing or publication'] };
  fs.writeFileSync(path.join(release, 'acceptance-report.json'), JSON.stringify(report, null, 2));
  fs.writeFileSync(path.join(release, 'VALIDATION-ONLY.txt'), 'Synthetic Auth configuration. This artifact validates packaging only. It is unsigned and is not a release or live-account build.\n');
  console.log(JSON.stringify(report, null, 2));
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
