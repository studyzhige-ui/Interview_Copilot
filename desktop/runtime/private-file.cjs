'use strict';
const fs = require('node:fs/promises');
const crypto = require('node:crypto');
async function writePrivateFileExclusively(location, data) {
  const temporary = `${location}.${crypto.randomBytes(12).toString('hex')}.tmp`;
  let handle, created = false;
  try {
    handle = await fs.open(temporary, 'wx', 0o600); created = true;
    await handle.writeFile(data); await handle.sync(); await handle.close(); handle = null;
    // Link publishes a complete same-filesystem file atomically and refuses
    // replacement. rename() could overwrite original protected settings.
    await fs.link(temporary, location);
  } finally {
    await handle?.close().catch(() => {});
    if (created) await fs.unlink(temporary).catch(() => {});
  }
}
module.exports = { writePrivateFileExclusively };
