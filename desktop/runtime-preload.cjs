'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('copilotRuntime', {
  command: action => ipcRenderer.invoke('runtime:command', action),
  onState: listener => { const handler = (_event, value) => listener(value); ipcRenderer.on('runtime:state', handler); return () => ipcRenderer.removeListener('runtime:state', handler); },
});
