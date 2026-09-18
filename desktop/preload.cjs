const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('careerDesktop',{
  command:(action,payload)=>ipcRenderer.invoke('career:command',action,payload),
  onState:callback=>{const listener=(_event,state)=>callback(state);ipcRenderer.on('career:state',listener);return()=>ipcRenderer.removeListener('career:state',listener)}
});
