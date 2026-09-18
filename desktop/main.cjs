const {app,BrowserWindow,WebContentsView,ipcMain,protocol,net,session,Menu}=require('electron');
const fs=require('node:fs');const path=require('node:path');const {pathToFileURL}=require('node:url');
const {webURL,safePath}=require('./policy.cjs');
protocol.registerSchemesAsPrivileged([{scheme:'career',privileges:{standard:true,secure:true,supportFetchAPI:true}}]);
const root=process.env.CAREER_PROTOTYPE_ROOT||path.resolve(__dirname,'../product-rebuild/prototypes');
const definitions=[['today','Today','today/today-orbit.html'],['profile','个人资料','personal-profile/index.html'],['market','岗位市场','job-market/index.html'],['applications','我的投递','job-market/index.html'],['editor','简历编辑器','resume-editor/index.html']];
let win,active=null,mode='home',rect={x:208,y:158,width:700,height:500},nextId=1,notice='';const tabs=new Map();
const smoke=process.argv.includes('--smoke');
function pages(){return definitions.map(([id,label,file])=>({id,label,available:fs.existsSync(path.join(root,file))}))}
function snapshot(){return {mode,active,notice,pages:pages(),tabs:[...tabs.values()].map(t=>({id:t.id,title:t.title,url:t.view.webContents.getURL()||t.url,loading:t.view.webContents.isLoading(),error:t.error||'',back:t.view.webContents.navigationHistory.canGoBack(),forward:t.view.webContents.navigationHistory.canGoForward()}))}}
function emit(){if(win&&!win.isDestroyed())win.webContents.send('career:state',snapshot())}
function layout(){if(!win)return;const [w,h]=win.getContentSize();for(const t of tabs.values()){t.view.setVisible(mode==='browser'&&t.id===active);t.view.setBounds({x:Math.max(0,Math.min(w,rect.x)),y:Math.max(0,Math.min(h,rect.y)),width:Math.max(0,Math.min(rect.width,w-rect.x)),height:Math.max(0,Math.min(rect.height,h-rect.y))})}}
function openTab(value,local=false){
  if(tabs.size>=12)throw Error('最多同时打开 12 个标签页，请先关闭不需要的页面');
  const url=local?value:webURL(value),id=String(nextId++);
  const view=new WebContentsView({webPreferences:{partition:local?'persist:career-pages':'persist:career-web',nodeIntegration:false,contextIsolation:true,sandbox:true,webSecurity:true}});
  const t={id,view,url,title:local?'应用页面':'新标签页',error:''};tabs.set(id,t);win.contentView.addChildView(view);active=id;mode='browser';
  const wc=view.webContents;
  wc.setWindowOpenHandler(({url})=>{try{openTab(url)}catch(e){notice=e.message;emit()}return {action:'deny'}});
  function guard(e,destination){try{if(local&&destination.startsWith('career://pages/'))return;webURL(destination)}catch{e.preventDefault()}}
  wc.on('will-navigate',guard);wc.on('will-redirect',guard);
  wc.on('page-title-updated',(_e,title)=>{t.title=title;emit()});
  for(const event of ['did-start-loading','did-stop-loading','did-navigate','did-navigate-in-page'])wc.on(event,emit);
  wc.on('did-fail-load',(_e,code,description,_url,isMainFrame)=>{if(isMainFrame&&code!==-3){t.error='页面未能打开：'+description;emit()}});
  wc.on('render-process-gone',()=>{t.error='此标签页已停止，请重新加载';emit()});
  wc.loadURL(url).catch(e=>{t.error=e.message;emit()});layout();emit();return t;
}
function closeTab(id){const t=tabs.get(id);if(!t)return;win.contentView.removeChildView(t.view);t.view.webContents.close();tabs.delete(id);if(active===id)active=[...tabs.keys()].at(-1)||null;if(!active)mode='home';layout();emit()}
async function command(action,payload){
  const current=tabs.get(active)?.view.webContents;
  switch(action){
    case 'state':return snapshot();
    case 'open':openTab(payload);break;
    case 'home':mode='home';layout();break;
    case 'select':if(!tabs.has(payload))throw Error('标签页不存在');active=payload;mode='browser';layout();break;
    case 'close':closeTab(payload);break;
    case 'navigate':if(current){const url=webURL(payload);tabs.get(active).error='';current.loadURL(url).catch(()=>{});mode='browser';layout()}else openTab(payload);break;
    case 'back':if(current?.navigationHistory.canGoBack())current.navigationHistory.goBack();break;
    case 'forward':if(current?.navigationHistory.canGoForward())current.navigationHistory.goForward();break;
    case 'reload':if(current){tabs.get(active).error='';current.reload()}break;
    case 'stop':current?.stop();break;
    case 'bounds':if(!payload||!['x','y','width','height'].every(k=>Number.isFinite(payload[k])&&payload[k]>=0&&payload[k]<20000))throw Error('无效布局');rect=Object.fromEntries(Object.entries(payload).filter(([k])=>['x','y','width','height'].includes(k)).map(([k,v])=>[k,Math.round(v)]));layout();return;
    case 'page':{const d=definitions.find(d=>d[0]===payload);if(!d||!fs.existsSync(path.join(root,d[2])))throw Error('这份已确认页面的源码当前不在项目目录中，恢复后即可接入。');openTab('career://pages/'+d[2]+(payload==='applications'?'?view=applications':''),true);break}
    default:throw Error('不支持的操作');
  }emit();return snapshot();
}
app.whenReady().then(async()=>{
  protocol.handle('career',request=>{try{const url=new URL(request.url),base=url.hostname==='ui'?path.join(__dirname,'ui'):url.hostname==='pages'?root:null;if(!base)return new Response('Not found',{status:404});const target=safePath(base,decodeURIComponent(url.pathname).slice(1));if(!/\.(html|css|js|svg|png|jpg|ttf|woff2?)$/i.test(target)||!fs.existsSync(target))return new Response('Not found',{status:404});const real=fs.realpathSync(target);safePath(fs.realpathSync(base),path.relative(fs.realpathSync(base),real));return net.fetch(pathToFileURL(real).href)}catch{return new Response('Not found',{status:404})}});
  for(const partition of ['persist:career-web','persist:career-pages']){
    const s=session.fromPartition(partition);s.setPermissionRequestHandler((_wc,_permission,callback)=>callback(false));s.setPermissionCheckHandler(()=>false);
    s.on('will-download',(_e,item)=>{notice='正在下载：'+item.getFilename();emit();item.once('done',(_e,status)=>{notice=status==='completed'?'下载完成：'+item.getFilename():status==='cancelled'?'已取消下载':'下载未完成';emit()})});
  }
  Menu.setApplicationMenu(null);
  win=new BrowserWindow({width:1440,height:950,minWidth:1024,minHeight:700,title:'Career OS',backgroundColor:'#f5f8fd',show:!smoke,webPreferences:{preload:path.join(__dirname,'preload.cjs'),nodeIntegration:false,contextIsolation:true,sandbox:true,webSecurity:true}});
  win.webContents.on('will-navigate',(e,url)=>{if(url!=='career://ui/index.html')e.preventDefault()});win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  ipcMain.handle('career:command',async(e,action,payload)=>{if(e.sender!==win.webContents||e.senderFrame!==win.webContents.mainFrame||e.senderFrame.url!=='career://ui/index.html')throw Error('无效请求来源');return command(action,payload)});
  win.on('resize',layout);win.on('closed',()=>{for(const t of tabs.values())if(!t.view.webContents.isDestroyed())t.view.webContents.close();tabs.clear();win=null});
  await win.loadURL('career://ui/index.html');
  if(smoke){try{const assert=require('node:assert/strict');const http=require('node:http');const server=http.createServer((_q,r)=>{r.end('<title>Browser smoke</title><input id="name">')});await new Promise(r=>server.listen(0,'127.0.0.1',r));const t=openTab('http://127.0.0.1:'+server.address().port);await new Promise((resolve,reject)=>{t.view.webContents.once('did-finish-load',resolve);t.view.webContents.once('did-fail-load',(_e,_c,m)=>reject(Error(m)))});assert.equal(t.view.webContents.getTitle(),'Browser smoke');assert.equal(t.view.webContents.getLastWebPreferences().nodeIntegration,false);await command('home');assert.equal(mode,'home');await command('select',t.id);assert.equal(active,t.id);closeTab(t.id);assert.equal(tabs.size,0);server.close();fs.writeFileSync(path.join(__dirname,'smoke-result.json'),JSON.stringify({passed:true,electron:process.versions.electron,checks:['application window','native web content load','remote Node disabled','view switch','tab disposal']},null,2));app.exit(0)}catch(e){fs.writeFileSync(path.join(__dirname,'smoke-result.json'),JSON.stringify({passed:false,error:e.stack}));app.exit(1)}}
});
app.on('window-all-closed',()=>app.quit());
