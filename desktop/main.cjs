'use strict';
const { app, BrowserWindow, ipcMain, protocol, net, session, shell, dialog, safeStorage } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { ComposeRuntime } = require('./runtime/compose.cjs');
const { CallbackGate, parseCallback } = require('./auth-callback.cjs');
const { installAudioPermissions } = require('./permissions.cjs');
const { safePath, webURL } = require('./policy.cjs');
if (process.argv.includes('--prototype')) { require('./prototype-main.cjs'); }
else {
  protocol.registerSchemesAsPrivileged([{ scheme: 'copilot-shell', privileges: { standard: true, secure: true } }]);
  const primary = app.requestSingleInstanceLock();
  if (!primary) app.quit();
  else {
    let setup, product, runtime, gate, origin = null, callback = null, incoming = null, choosingDirectory = false;
    let status = { canStop: false, phase: 'idle', message: '启动本地工作区前，请先安装并启动 Docker Desktop，并选择 Linux 容器模式。' };
    const emit = () => { if (setup && !setup.isDestroyed()) setup.webContents.send('runtime:state', status); };
    const setStatus = (phase, message) => { status = { ...status, phase, message, ready: !!origin }; emit(); };
    const offerCallback = value => {
      const parsed = parseCallback(value); if (!parsed) return;
      if (!gate) { incoming = value; return; }
      if (parsed.noticeOnly) { setStatus('error', parsed.error); setup?.show(); setup?.focus(); return; }
      const accepted = gate.consume(value);
      if (!accepted) { setStatus('error', '此邮件链接没有对应的待完成操作、已过期或已使用。请从应用重新发送邮件'); return; }
      callback = accepted;
      if (product && !product.isDestroyed()) { product.show(); product.focus(); product.webContents.send('auth:callback-ready'); }
      else if (setup) { setup.show(); setup.focus(); setStatus('idle', '已收到邮箱返回，请启动原本的本地工作区以继续验证'); }
    };
    app.on('open-url', (event, url) => { event.preventDefault(); offerCallback(url); });
    app.on('second-instance', (_event, argv) => { const urls = argv.filter(value => parseCallback(value)); if (urls.length === 1) offerCallback(urls[0]); else (product || setup)?.focus(); });
    const firstURLs = process.argv.filter(value => parseCallback(value)); if (firstURLs.length === 1) incoming = firstURLs[0];
    const isSetup = event => event.sender === setup?.webContents && event.senderFrame === setup.webContents.mainFrame && event.senderFrame.url === 'copilot-shell://setup/index.html';
    const isProduct = event => event.sender === product?.webContents && event.senderFrame === product.webContents.mainFrame && origin && new URL(event.senderFrame.url).origin === origin;
    function productWindow() {
      if (product && !product.isDestroyed()) { product.show(); product.focus(); return; }
      const partition = 'persist:interview-copilot-product';
      const productSession = session.fromPartition(partition);
      installAudioPermissions(productSession, { current: () => product?.webContents, origin: () => origin, ask: async () => {
        const answer = await dialog.showMessageBox(product, { type: 'question', buttons: ['不允许', '允许本次使用麦克风'], defaultId: 0, cancelId: 0, message: '允许当前本地工作区使用麦克风？', detail: '仅在你开始录音或语音面试时使用。你仍可选择文字面试。' });
        return answer.response === 1;
      } });
      product = new BrowserWindow({ width: 1440, height: 950, minWidth: 900, minHeight: 650, title: 'Interview Copilot', backgroundColor: '#fafaf9', webPreferences: { preload: path.join(__dirname, 'product-preload.cjs'), partition, nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true } });
      const guard = (event, destination) => { try { if (new URL(destination).origin !== origin) event.preventDefault(); } catch { event.preventDefault(); } };
      product.webContents.on('will-navigate', guard); product.webContents.on('will-redirect', guard);
      product.webContents.setWindowOpenHandler(({ url }) => { try { void shell.openExternal(webURL(url)); } catch { /* Privileged schemes are never forwarded. */ } return { action: 'deny' }; });
      product.on('closed', () => { product = null; });
      void product.loadURL(origin + '/auth').catch(() => setStatus('error', '本地界面加载失败，请检查服务状态后重试'));
    }
    app.whenReady().then(async () => {
      app.setName('Interview Copilot');
      const root = path.join(app.getPath('userData'), 'local-workspace');
      fs.mkdirSync(root, { recursive: true, mode: 0o700 });
      const pendingPath = path.join(root, 'pending-auth.json');
      gate = new CallbackGate({ read: () => { try { return JSON.parse(fs.readFileSync(pendingPath, 'utf8')); } catch { return null; } }, write: value => { if (value) fs.writeFileSync(pendingPath, JSON.stringify(value), { mode: 0o600 }); else fs.rmSync(pendingPath, { force: true }); } });
      protocol.handle('copilot-shell', request => {
        try {
          const url = new URL(request.url); if (url.hostname !== 'setup' || url.search || url.hash) throw new Error();
          const target = safePath(path.join(__dirname, 'setup'), decodeURIComponent(url.pathname).slice(1));
          if (!/\.(html|css|js)$/.test(target)) throw new Error();
          return net.fetch(pathToFileURL(target).href);
        } catch { return new Response('Not found', { status: 404 }); }
      });
      setup = new BrowserWindow({ width: 740, height: 760, resizable: true, title: 'Interview Copilot · 本地服务', webPreferences: { preload: path.join(__dirname, 'runtime-preload.cjs'), nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true } });
      setup.webContents.on('will-navigate', (event, url) => { if (url !== 'copilot-shell://setup/index.html') event.preventDefault(); });
      setup.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
      setup.on('closed', () => { setup = null; });
      try {
        if (!safeStorage.isEncryptionAvailable()) throw new Error('系统凭据保护不可用，无法安全保存本地运行配置');
        const resources = app.isPackaged ? path.join(process.resourcesPath, 'runtime') : path.join(__dirname, '.runtime');
        const manifest = JSON.parse(fs.readFileSync(path.join(resources, 'desktop-runtime.json'), 'utf8'));
        runtime = new ComposeRuntime({ root, resources, bundle: manifest.bundle, auth: manifest.auth, encode: value => safeStorage.encryptString(value), decode: value => safeStorage.decryptString(value) });
        status.canStop = await runtime.hasWorkspace();
        Object.assign(status, await runtime.dataDirectoryInfo());
      } catch (error) { setStatus('error', error.code === 'ENOENT' ? '发行包缺少本地服务资源。开发者请先执行 prepare-runtime；不会自动下载未知安装包' : error.message); }
      ipcMain.handle('runtime:command', async (event, action) => {
        if (!isSetup(event)) throw new Error('无效请求来源');
        if (action === 'state') return status;
        if (action === 'docker-guide') { await shell.openExternal('https://docs.docker.com/desktop/setup/install/windows-install/'); return status; }
        if (!runtime) throw new Error('本地服务资源尚未配置');
        if (choosingDirectory) throw new Error('请先完成或取消资料目录选择');
        try {
          if (action === 'choose-data-directory') {
            if (runtime.busy) throw new Error('请先等待当前服务操作完成');
            choosingDirectory = true;
            try {
              if (!(await runtime.dataDirectoryInfo()).canChooseDirectory) throw new Error('已有工作区不能直接更换目录；迁移需要先复制和核验资料');
              if (!isSetup(event)) throw new Error('目录选择已失效，请重新打开设置');
              setStatus('choosing', '请选择存放资料和缓存的本地文件夹');
              const result = await dialog.showOpenDialog(setup, { title: '选择资料与缓存的存放位置', properties: ['openDirectory', 'createDirectory'] });
              if (!isSetup(event)) throw new Error('目录选择已失效，请重新打开设置');
              if (!result.canceled && result.filePaths.length === 1) Object.assign(status, await runtime.selectDataDirectory(result.filePaths[0]));
              setStatus('idle', result.canceled ? '资料位置未修改' : '启动时会创建本应用的独立资料子目录，原有文件不会被覆盖');
            } finally { choosingDirectory = false; }
          }
          else if (action === 'check') { await runtime.check(); setStatus('idle', 'Docker Desktop 已就绪，可以启动本地工作区'); }
          else if (action === 'start') { setStatus('starting', '正在构建并启动本地服务。首次启动需要联网下载依赖，请保持 Docker Desktop 运行'); const result = await runtime.start(); origin = result.origin; status.canStop = true; Object.assign(status, await runtime.dataDirectoryInfo()); setStatus('ready', '本地数据库、任务服务和界面已就绪'); productWindow(); }
          else if (action === 'open') { if (!origin) throw new Error('请先启动本地服务'); productWindow(); }
          else if (action === 'stop') { setStatus('stopping', '正在停止本应用的本地服务，资料与数据库卷会保留'); await runtime.stop(); product?.close(); origin = null; setStatus('idle', '本地服务已停止，资料和密钥仍保留'); }
          else throw new Error('不支持的操作');
          return status;
        } catch (error) { status.canStop = await runtime.hasWorkspace(); try { Object.assign(status, await runtime.dataDirectoryInfo()); } catch { status.canChooseDirectory = false; } setStatus('error', error.message); throw error; }
      });
      ipcMain.handle('auth:begin', (event, purpose) => { if (!isProduct(event)) throw new Error('无效请求来源'); return gate.begin(purpose); });
      ipcMain.handle('auth:cancel', (event, id) => { if (!isProduct(event)) throw new Error('无效请求来源'); gate.cancel(id); });
      ipcMain.handle('auth:take', event => { if (!isProduct(event)) throw new Error('无效请求来源'); const value = callback; callback = null; return value; });
      await setup.loadURL('copilot-shell://setup/index.html');
      // Registration is part of an installed application, never a side effect
      // of running unit tests or the development prototype.
      if (app.isPackaged && !app.setAsDefaultProtocolClient('interview-copilot')) setStatus('error', '未能注册邮箱返回链接，请修复安装后再使用注册或找回密码');
      if (incoming) { const value = incoming; incoming = null; offerCallback(value); }
    }).catch(error => { dialog.showErrorBox('Interview Copilot 无法启动', error.message); app.quit(); });
    app.on('window-all-closed', () => app.quit());
  }
}
