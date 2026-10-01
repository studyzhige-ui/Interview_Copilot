'use strict';
const assert = require('node:assert/strict');
const path = require('node:path');
const { build, Platform, Arch } = require('electron-builder');
assert.equal(process.platform, 'win32', 'Build this installer on the disposable Windows runner');
assert.equal(process.env.CI, 'true');
assert.equal(process.env.IC_DESKTOP_ACCEPTANCE, '1');
assert.equal(process.env.IC_SUPABASE_URL, 'https://fixture.supabase.co');
assert.equal(process.env.IC_SUPABASE_PUBLISHABLE_KEY, 'sb_publishable_synthetic_fixture');
const projectDir = path.resolve(__dirname, '..');
require('./prepare-runtime.cjs');
// Structured builder options avoid PowerShell/npm rewriting dotted CLI flags.
// The pinned builder merges this override into package.json's build settings.
build({ projectDir, targets: Platform.WINDOWS.createTarget('nsis', Arch.x64), publish: 'never', config: { artifactName: 'Interview-Copilot-acceptance-fixture.exe' } })
  .catch(error => { console.error(error.message); process.exitCode = 1; });
