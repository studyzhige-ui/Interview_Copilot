const fs=require('fs'),vm=require('vm');let html='';const handlers={};const app={set innerHTML(v){html=v},get innerHTML(){return html},querySelector(){return null}};
const context={URL,URLSearchParams,location:{search:'?view=applications&demo=1',href:'http://127.0.0.1:8790/market/index.html?view=applications&demo=1'},history:{replaceState(){}},localStorage:{getItem(){return null},setItem(){}},load:()=>[],save:()=>{},render:()=>context.applications(),app,view:'market',current:null,esc:v=>String(v??''),nodes:w=>w.nodes?.length?w.nodes:[{id:'preparation',name:'准备投递',time:w.createdAt}],document:{body:{classList:{toggle(){}}},addEventListener(type,handler){handlers[type]=handler}},console};vm.createContext(context);vm.runInContext(fs.readFileSync('product-rebuild/prototypes/job-market/applications.js','utf8'),context);
for(const text of ['进行中 3 个岗位','待投递 1 个岗位','已结束 3 个岗位'])if(!html.includes(text))throw Error('Missing overview '+text);
const tencent=html.split('data-card-id="demo-a"')[1].split('</article>')[0];if(tencent.includes('二面')||tencent.includes('Offer'))throw Error('Unknown stages rendered');
const waiting=html.split('data-card-id="demo-c"')[1].split('</article>')[0];if(waiting.includes('测评')||waiting.includes('面试')||waiting.includes('Offer'))throw Error('Unknown waiting stages');
console.log('Overview: active 3 (includes waiting 1), ended 3; no speculative Tencent or waiting stages.');

handlers.change({target:{id:'application-stage',value:'一面'}});
if(!html.includes('data-card-id="demo-a"')||html.includes('data-card-id="demo-b"')||html.includes('data-card-id="demo-c"'))throw Error('Current-stage filter failed');
handlers.change({target:{id:'application-stage',value:''}});
handlers.change({target:{id:'application-sort',value:'stage-early'}});
if(!(html.indexOf('data-card-id="demo-c"')<html.indexOf('data-card-id="demo-a"')&&html.indexOf('data-card-id="demo-a"')<html.indexOf('data-card-id="demo-b"')))throw Error('Stage sort failed');
handlers.change({target:{id:'application-sort',value:'node-old'}});
if(!(html.indexOf('data-card-id="demo-c"')<html.indexOf('data-card-id="demo-a"')))throw Error('Node time sort failed');
console.log('Current-stage filter and progress/time sort passed.');
const clickSort=kind=>{const b={dataset:{directSort:kind},hasAttribute(){return false}};handlers.click({target:{closest:q=>q==='button'?b:null},preventDefault(){},stopImmediatePropagation(){}})};
handlers.change({target:{id:'application-sort',value:'default'}});
for(const [kind,label] of [['time','按当前节点时间'],['stage','按进程']]){
 clickSort(kind);if(!html.includes(label+'排序：降序'))throw Error(kind+' descending toggle failed');
 clickSort(kind);if(!html.includes(label+'排序：升序'))throw Error(kind+' ascending toggle failed');
 clickSort(kind);
 if(!html.includes('value="default" selected')||html.includes('class="direct-sort sort-active"'))throw Error(kind+' default toggle failed');
 if(!(html.indexOf('data-card-id="demo-a"')<html.indexOf('data-card-id="demo-b"')&&html.indexOf('data-card-id="demo-b"')<html.indexOf('data-card-id="demo-c"')))throw Error(kind+' original order not restored');
 if(html.includes('data-app-reset'))throw Error('Reset button should not render');
}
console.log('Both sort buttons cycle descending / ascending / original order; reset removed.');
