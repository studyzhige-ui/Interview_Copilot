'use strict';
const path = require('node:path');
const fs = require('node:fs/promises');
const crypto = require('node:crypto');
const net = require('node:net');
const { spawn } = require('node:child_process');
const { absoluteLocalDirectory, selectedParent, createDataDirectory, verifyDataDirectory, discardUncommittedDataDirectory } = require('./data-directory.cjs');
const { writePrivateFileExclusively: writeSettingsExclusively } = require('./private-file.cjs');
const REQUIRED = ['db', 'redis', 'api', 'frontend', 'worker-turns', 'worker-transcription', 'worker-pipeline', 'worker-jobs', 'beat'];
const LABEL = 'io.interview-copilot.installation';
// Values injected after `compose config` must survive the second interpolation
// pass literally. Never re-escape the model already serialized by Compose.
const composeLiteral = value => value.replaceAll('$', () => '$$');
function projectName(id) { if (!/^[a-f0-9]{24}$/.test(id)) throw new Error('本地工作区标识无效'); return `interview-copilot-${id}`; }
function publicConfig(value) {
  if (value?.provider !== 'supabase') throw new Error('发行包缺少统一账号配置');
  let url; try { url = new URL(value.url); } catch { throw new Error('统一账号地址无效'); }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/') throw new Error('统一账号地址必须是 HTTPS 项目源地址');
  if (typeof value.publishableKey !== 'string' || !/^sb_publishable_[A-Za-z0-9_-]+$/.test(value.publishableKey)) throw new Error('发行包必须使用公开 publishable key');
  return { provider: 'supabase', url: url.origin, publishableKey: value.publishableKey, emailDelivery: value.emailDelivery === 'custom_smtp' ? 'custom_smtp' : 'team_only' };
}
function environment(state, auth) {
  const values = {
    APP_EDITION: 'community', AUTH_PROVIDER: 'supabase', SUPABASE_URL: auth.url,
    SUPABASE_PUBLISHABLE_KEY: auth.publishableKey, SUPABASE_EMAIL_DELIVERY: auth.emailDelivery,
    SECRET_KEY: state.secret, POSTGRES_USER: 'postgres', POSTGRES_PASSWORD: state.databasePassword,
    POSTGRES_DB: 'interview_copilot', STORAGE_BACKEND: 'filesystem', STORAGE_DIR: '/app/data/storage', STORAGE_MIN_FREE_BYTES: '67108864',
    DATABASE_URL: `postgresql://postgres:${state.databasePassword}@db:5432/interview_copilot`,
    REDIS_URL: 'redis://redis:6379/0', CORS_ORIGINS: `http://127.0.0.1:${state.port}`,
    APP_EXTRAS: '', UVICORN_WORKERS: '2',
  };
  for (const value of Object.values(values)) if (/[\r\n\0]/.test(value)) throw new Error('本地配置包含无效字符');
  return Object.entries(values).map(([key, value]) => `${key}=${value}`).join('\n') + '\n';
}
function ownedModel(model, state, dataRoot) {
  const project = projectName(state.id);
  if (REQUIRED.some(name => !model.services?.[name])) throw new Error('发行包服务配置不完整');
  for (const [name, service] of Object.entries(model.services)) {
    delete service.container_name;
    service.labels = { ...(service.labels || {}), [LABEL]: state.id };
    if (service.build) service.image = `${project}-${name === 'db' || name === 'frontend' ? name : 'backend'}:${state.bundle.slice(0, 12)}`;
    // Infrastructure is private to this Compose network. The product's API
    // serves scoped file capabilities; only its loopback port is published.
    delete service.ports;
    if (service.volumes) service.volumes = service.volumes.map(volume => volume.type === 'bind' && volume.target === '/app/data' ? { ...volume, source: composeLiteral(dataRoot) } : volume);
  }
  model.services.frontend.ports = [{ target: 80, published: String(state.port), host_ip: '127.0.0.1', protocol: 'tcp' }];
  model.name = project;
  return model;
}
function validateState(state) {
  projectName(state?.id);
  if (!/^[a-f0-9]{64}$/.test(state.bundle || '') || ![state.port, state.storagePort].every(port => Number.isInteger(port) && port >= 1024 && port <= 65535) || state.port === state.storagePort || !['secret', 'databasePassword', 'storageUser', 'storagePassword'].every(key => typeof state[key] === 'string' && /^[A-Za-z0-9_-]{24,128}$/.test(state[key]))) throw new Error('本地工作区配置损坏；不会覆盖或重新生成密钥');
  if (state.dataDirectory !== undefined) absoluteLocalDirectory(state.dataDirectory);
  return state;
}
function rows(output) { const value = output.trim(); if (!value) return []; if (value.startsWith('[')) return JSON.parse(value); return value.split('\n').map(line => JSON.parse(line)); }
async function freePort() { return new Promise((resolve, reject) => { const server = net.createServer(); server.once('error', reject); server.listen(0, '127.0.0.1', () => { const port = server.address().port; server.close(error => error ? reject(error) : resolve(port)); }); }); }
async function assertPortFree(port) { return new Promise((resolve, reject) => { const server = net.createServer(); server.once('error', () => reject(new Error(`本地端口 ${port} 已被其他程序占用，请关闭冲突程序后重试`))); server.listen(port, '127.0.0.1', () => server.close(resolve)); }); }
function childEnvironment(source = process.env) {
  const allowed = new Set(['PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMDATA', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'TEMP', 'TMP', 'HOME']);
  return { ...Object.fromEntries(Object.entries(source).filter(([key]) => allowed.has(key.toUpperCase()))), DOCKER_CLI_HINTS: 'false' };
}
function command(executable, args, { cwd, timeout = 30000, signal, onFailureDiagnostic } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, { cwd, windowsHide: true, shell: false, env: childEnvironment() });
    let output = '', errors = '', done = false;
    const finish = (error, value) => { if (done) return; done = true; clearTimeout(timer); signal?.removeEventListener('abort', abort); error ? reject(error) : resolve(value); };
    const abort = () => { child.kill(); finish(new Error('本地服务操作已取消')); };
    const timer = setTimeout(() => { child.kill(); finish(new Error('本地服务操作超时，请检查 Docker Desktop 状态')); }, timeout);
    signal?.addEventListener('abort', abort, { once: true });
    child.stdout.on('data', chunk => { output += chunk; if (output.length > 8 * 1024 * 1024) { child.kill(); finish(new Error('Docker 返回的数据过大')); } });
    child.stderr.on('data', chunk => { errors = (errors + chunk).slice(-16000); });
    child.on('error', () => finish(new Error('未找到可运行的 Docker Desktop，请先安装并启动它')));
    child.on('exit', code => {
      if (code === 0) return finish(null, output);
      // Diagnostics are opt-in for the disposable acceptance harness. Renderer
      // errors never include CLI output, which can contain interpolated secrets.
      if (typeof onFailureDiagnostic === 'function') { try { onFailureDiagnostic(errors); } catch { /* Never replace the original failure. */ } }
      finish(new Error(`Docker 操作失败（退出码 ${code ?? 'unknown'}），请查看 Docker Desktop；本地数据仍保留`));
    });
    if (signal?.aborted) abort();
  });
}
class ComposeRuntime {
  constructor({ root, resources, bundle, auth, encode, decode, run = command, platform = process.platform }) {
    this.root = root; this.resources = resources; this.bundle = bundle; this.auth = publicConfig(auth);
    this.encode = encode; this.decode = decode; this.platform = platform;
    const endpoint = platform === 'win32' ? 'npipe:////./pipe/docker_engine' : 'unix:///var/run/docker.sock';
    this.run = (executable, args, options) => run(executable, ['--host', endpoint, ...args], options); this.busy = false; this.state = null;
  }
  async check() {
    const info = JSON.parse(await this.run('docker', ['info', '--format', '{{json .}}']));
    if (info.OSType !== 'linux') throw new Error('请将 Docker Desktop 切换到 Linux 容器模式');
    if (this.platform === 'win32' && !String(info.OperatingSystem).includes('Docker Desktop')) throw new Error('当前本地管道不是受支持的 Docker Desktop 引擎');
    await this.run('docker', ['compose', 'version', '--short']);
    return { docker: true, linuxContainers: true };
  }
  async hasWorkspace() {
    try { validateState(JSON.parse(this.decode(await fs.readFile(path.join(this.root, 'workspace.enc'))))); return true; } catch { return false; }
  }
  async dataDirectoryInfo() {
    try {
      const state = validateState(JSON.parse(this.decode(await fs.readFile(path.join(this.root, 'workspace.enc')))));
      return { canChooseDirectory: false, dataDirectory: state.dataDirectory || path.join(this.root, 'data'), dataDirectoryIsParent: false };
    } catch (error) {
      if (error.code !== 'ENOENT') throw new Error('原工作区配置无法读取；不会修改资料位置或重置密钥');
      return { canChooseDirectory: true, dataDirectory: this.selectedDataParent || path.join(this.root, 'data'), dataDirectoryIsParent: !!this.selectedDataParent };
    }
  }
  async selectDataDirectory(directory) {
    if (this.busy || !(await this.dataDirectoryInfo()).canChooseDirectory) throw new Error('已有工作区不能直接更换资料目录，请先完成备份、复制与核验');
    const selected = await selectedParent(directory);
    if (this.busy || !(await this.dataDirectoryInfo()).canChooseDirectory) throw new Error('工作区已启动，不能直接修改资料位置');
    this.selectedDataParent = selected;
    return this.dataDirectoryInfo();
  }
  async load({ create = true, allowBundleMismatch = false } = {}) {
    await fs.mkdir(this.root, { recursive: true, mode: 0o700 });
    const location = path.join(this.root, 'workspace.enc');
    try { this.state = JSON.parse(this.decode(await fs.readFile(location))); }
    catch (error) { if (error.code !== 'ENOENT') throw new Error('本地工作区配置无法读取；请保留此目录并从备份恢复，不会自动重置密钥'); }
    if (this.state) {
      validateState(this.state);
      if (!allowBundleMismatch && this.state.bundle !== this.bundle) throw new Error('此工作区来自另一版本。请先完成数据库和资料备份及升级确认，当前版本不会自动迁移已有资料');
      return this.state;
    }
    if (!create) throw new Error('尚未创建本地工作区');
    const state = { id: crypto.randomBytes(12).toString('hex'), bundle: this.bundle, port: await freePort(), storagePort: await freePort(), secret: crypto.randomBytes(48).toString('base64url'), databasePassword: crypto.randomBytes(32).toString('hex'), storageUser: crypto.randomBytes(12).toString('hex'), storagePassword: crypto.randomBytes(32).toString('hex') };
    while (state.storagePort === state.port) state.storagePort = await freePort();
    state.dataDirectory = await createDataDirectory(this.root, state.id, this.selectedDataParent);
    validateState(state);
    try { await writeSettingsExclusively(location, this.encode(JSON.stringify(state))); }
    catch (error) { await discardUncommittedDataDirectory(state.dataDirectory, state.id); throw error; }
    this.state = state;
    return this.state;
  }
  async configured(action) {
    const state = await this.load(), project = projectName(state.id);
    const temporary = await fs.mkdtemp(path.join(this.root, '.command-'));
    try {
      const envPath = path.join(temporary, '.env');
      await fs.writeFile(envPath, environment(state, this.auth), { mode: 0o600 });
      let template = await fs.readFile(path.join(this.resources, 'docker-compose.yml'), 'utf8');
      if (!template.includes('env_file: .env')) throw new Error('发行包 Compose 模板版本不受支持');
      template = template.replaceAll('env_file: .env', () => `env_file: ${JSON.stringify(composeLiteral(envPath))}`);
      const source = path.join(temporary, 'source.yml'), generated = path.join(temporary, 'owned.json');
      await fs.writeFile(source, template, { mode: 0o600 });
      const prefix = ['compose', '--project-name', project, '--project-directory', this.resources, '--env-file', envPath];
      const model = JSON.parse(await this.run('docker', [...prefix, '-f', source, '--profile', 'full', 'config', '--format', 'json']));
      let data = state.dataDirectory ? await verifyDataDirectory(state.dataDirectory, state.id) : path.join(this.root, 'data');
      if (!state.dataDirectory) { await fs.mkdir(data, { recursive: true, mode: 0o700 }); data = await selectedParent(data); }
      await fs.writeFile(generated, JSON.stringify(ownedModel(model, state, data)), { mode: 0o600 });
      return await action([...prefix, '-f', generated, '--profile', 'full'], state);
    } finally { await fs.rm(temporary, { recursive: true, force: true }); }
  }
  async inspectOwned(state) {
    const ids = rows(await this.run('docker', ['ps', '-a', '--filter', `label=com.docker.compose.project=${projectName(state.id)}`, '--format', '{{json .}}']));
    if (!ids.length) return [];
    if (!ids.every(row => /^[a-f0-9]{12,64}$/.test(row.ID))) throw new Error('Docker 容器标识无效');
    const inspections = JSON.parse(await this.run('docker', ['inspect', ...ids.map(row => row.ID)]));
    for (const item of inspections) {
      if (item.Config?.Labels?.[LABEL] !== state.id) throw new Error('检测到工作区标识冲突，未操作已有容器');
      if (!/^[a-f0-9]{64}$/.test(item.Id || '')) throw new Error('Docker 容器标识无效');
    }
    return inspections;
  }
  async start() {
    if (this.busy) throw new Error('本地服务操作正在进行，请稍候'); this.busy = true;
    try {
      await this.check();
      return await this.configured(async (prefix, state) => {
        const previous = await this.inspectOwned(state);
        const published = previous.flatMap(item => Object.values(item.NetworkSettings?.Ports || {}).flat()).filter(Boolean).map(item => Number(item.HostPort));
        for (const port of [state.port]) if (!published.includes(port)) await assertPortFree(port);
        await this.run('docker', [...prefix, 'up', '-d', '--build', '--wait', '--wait-timeout', '240'], { timeout: 20 * 60 * 1000 });
        const running = await this.inspectOwned(state);
        const ready = new Set(running.filter(item => item.State?.Running).map(item => item.Config.Labels['com.docker.compose.service']));
        if (REQUIRED.some(name => !ready.has(name))) throw new Error('部分本地服务尚未启动，数据仍保留，请检查 Docker Desktop');
        const origin = `http://127.0.0.1:${state.port}`;
        const response = await fetch(origin + '/api/v1/health/ready', { signal: AbortSignal.timeout(5000), redirect: 'error' });
        const status = await response.json();
        if (!response.ok || status.status !== 'ready' || status.dependencies?.database !== 'ok' || status.dependencies?.redis !== 'ok') throw new Error('本地数据库或任务服务尚未就绪');
        return { origin, project: projectName(state.id) };
      });
    } finally { this.busy = false; }
  }
  async stop() {
    if (this.busy) throw new Error('请等待当前启动操作完成后再停止服务'); this.busy = true;
    try {
      await this.check();
      const state = await this.load({ create: false, allowBundleMismatch: true });
      const owned = await this.inspectOwned(state);
      if (owned.length) await this.run('docker', ['stop', '--time', '30', ...owned.map(item => item.Id)], { timeout: 60000 });
      return { stopped: true, dataRetained: true };
    }
    finally { this.busy = false; }
  }
}
module.exports = { ComposeRuntime, command, ownedModel, environment, publicConfig, rows, projectName, REQUIRED, LABEL, validateState, childEnvironment, writeSettingsExclusively };
