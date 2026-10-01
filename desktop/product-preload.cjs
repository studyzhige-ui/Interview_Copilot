'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('copilotDesktopAuth', {
  begin: purpose => ipcRenderer.invoke('auth:begin', purpose),
  cancel: id => ipcRenderer.invoke('auth:cancel', id),
  take: () => ipcRenderer.invoke('auth:take'),
  onReady: listener => { const handler = () => listener(); ipcRenderer.on('auth:callback-ready', handler); return () => ipcRenderer.removeListener('auth:callback-ready', handler); },
});
