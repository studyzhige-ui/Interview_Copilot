'use strict';
/** Assemble only audited runtime sources. Never copy .env, user data or credentials. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { publicConfig } = require('../runtime/compose.cjs');
const root = path.resolve(__dirname, '../..'), target = path.resolve(__dirname, '../.runtime');
const auth = publicConfig({ provider: 'supabase', url: process.env.IC_SUPABASE_URL, publishableKey: process.env.IC_SUPABASE_PUBLISHABLE_KEY, emailDelivery: process.env.IC_SUPABASE_EMAIL_DELIVERY });
const entries = ['docker-compose.yml', 'pyproject.toml', 'README.md', 'backend/Dockerfile', 'backend/docker-entrypoint.sh', 'backend/app', 'alembic', 'alembic.ini', 'infra/postgres', 'nginx', 'frontend', 'scripts/consistency_scan.py', 'scripts/init_models.py', 'scripts/reingest_hybrid.py'];
const excluded = new Set(['node_modules', '__pycache__', '.pytest_cache', 'dist', '.git', '.env', '.env.local', '.env.production', 'test-results']);
fs.rmSync(target, { recursive: true, force: true }); fs.mkdirSync(target, { recursive: true });
for (const name of entries) fs.cpSync(path.join(root, name), path.join(target, name), { recursive: true, dereference: false, filter: source => {
  const base = path.basename(source); if (excluded.has(base) || base.endsWith('.pyc') || base.endsWith('.tsbuildinfo') || base.startsWith('.env')) return false;
  if (fs.lstatSync(source).isSymbolicLink()) throw new Error(`Runtime source cannot contain symlinks: ${path.relative(root, source)}`);
  return true;
} });
const files = [];
function walk(directory) { for (const entry of fs.readdirSync(directory, { withFileTypes: true }).sort((a,b) => a.name.localeCompare(b.name))) { const location = path.join(directory, entry.name); if (entry.isDirectory()) walk(location); else files.push({ path: path.relative(target, location).split(path.sep).join('/'), sha256: crypto.createHash('sha256').update(fs.readFileSync(location)).digest('hex') }); } }
walk(target);
const bundle = crypto.createHash('sha256').update(JSON.stringify(files)).digest('hex');
fs.writeFileSync(path.join(target, 'desktop-runtime.json'), JSON.stringify({ bundle, auth, files }, null, 2));
console.log(`Prepared ${files.length} runtime files, bundle ${bundle}; no private configuration copied`);
