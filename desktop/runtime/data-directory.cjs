'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const { writePrivateFileExclusively } = require('./private-file.cjs');
const OWNER_FILE = '.copilot-data-owner.json';
function absoluteLocalDirectory(value) {
  if (typeof value !== 'string' || !path.isAbsolute(value) || /[\0\r\n]/.test(value) || (process.platform === 'win32' && value.startsWith('\\\\'))) throw new Error('请选择此电脑上的本地文件夹');
  return path.resolve(value);
}
async function directoryChainWithoutLinks(directory) {
  let cursor = directory, leaf;
  for (;;) {
    const info = await fs.lstat(cursor, { bigint: true });
    if (!info.isDirectory() || info.isSymbolicLink()) throw new Error('资料目录不能是链接或普通文件');
    leaf ??= info;
    const parent = path.dirname(cursor);
    if (parent === cursor) return leaf;
    cursor = parent;
  }
}
async function directoryWithoutLink(directory) {
  const before = await directoryChainWithoutLinks(directory);
  const actual = await fs.realpath(directory);
  // Windows may expand a legitimate 8.3 name without changing the directory.
  // Reject links in either ancestry and compare filesystem identity, not spelling.
  const canonical = await directoryChainWithoutLinks(actual);
  const after = await directoryChainWithoutLinks(directory);
  if (before.ino !== canonical.ino || before.dev !== canonical.dev || before.ino !== after.ino || before.dev !== after.dev) throw new Error('资料目录路径发生了重定向，请恢复原目录后重试');
  return actual;
}
async function selectedParent(value) {
  const directory = absoluteLocalDirectory(value);
  return directoryWithoutLink(directory);
}
async function createDataDirectory(workspaceRoot, installation, parent) {
  if (!/^[a-f0-9]{24}$/.test(installation)) throw new Error('本地工作区标识无效');
  let directory;
  if (parent) {
    const base = await selectedParent(parent), group = path.join(base, 'Interview Copilot');
    try { await fs.mkdir(group, { mode: 0o700 }); } catch (error) { if (error.code !== 'EEXIST') throw error; }
    await directoryWithoutLink(group);
    directory = path.join(group, installation);
  } else directory = path.join(workspaceRoot, 'data');
  // An existing directory without the protected installation settings must not
  // be reinitialized with a new identity/key, even when it appears empty.
  try { await fs.mkdir(directory, { mode: 0o700 }); }
  catch (error) { if (error.code === 'EEXIST') throw new Error('资料目录已存在；请保留旧资料及原配置，不会自动接管或覆盖'); throw error; }
  const created = await fs.lstat(directory, { bigint: true });
  try {
    directory = await directoryWithoutLink(directory);
    await writePrivateFileExclusively(path.join(directory, OWNER_FILE), JSON.stringify({ version: 1, installation }));
  } catch (error) {
    // Only the same newly created, still-empty directory may be removed. A
    // partial marker never becomes final; any concurrently added files remain.
    const current = await fs.lstat(directory, { bigint: true }).catch(() => null);
    if (current?.isDirectory() && !current.isSymbolicLink() && current.ino === created.ino && current.dev === created.dev) await fs.rmdir(directory).catch(() => {});
    throw error;
  }
  return directory;
}
async function verifyDataDirectory(directory, installation) {
  absoluteLocalDirectory(directory); directory = await directoryWithoutLink(directory);
  const marker = path.join(directory, OWNER_FILE), info = await fs.lstat(marker);
  if (!info.isFile() || info.isSymbolicLink()) throw new Error('资料目录的归属标记无效');
  const owner = JSON.parse(await fs.readFile(marker, 'utf8'));
  if (owner.version !== 1 || owner.installation !== installation) throw new Error('资料目录属于另一工作区；未启动或移动资料');
  return directory;
}
async function discardUncommittedDataDirectory(directory, installation) {
  // A failed first settings write may leave only our newly created marker.
  // Never recursively remove anything, adopt preexisting data, or remove a file
  // someone added while the write was failing.
  try {
    await verifyDataDirectory(directory, installation);
    const entries = await fs.readdir(directory);
    if (entries.length !== 1 || entries[0] !== OWNER_FILE) return false;
    await fs.unlink(path.join(directory, OWNER_FILE));
    try { await fs.rmdir(directory); return true; }
    catch {
      // If content arrived concurrently, preserve it and restore our marker
      // only when the directory still resolves to this same literal path.
      await directoryWithoutLink(directory);
      await writePrivateFileExclusively(path.join(directory, OWNER_FILE), JSON.stringify({ version: 1, installation })).catch(() => {});
      return false;
    }
  } catch { return false; }
}
module.exports = { absoluteLocalDirectory, selectedParent, createDataDirectory, verifyDataDirectory, discardUncommittedDataDirectory };
