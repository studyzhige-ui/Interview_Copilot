
(()=>{const root=document.getElementById('career-today');const q=s=>root.querySelector(s);const qa=s=>[...root.querySelectorAll(s)];let year=2026,month=8,selected=null,allAgenda=false,toastTimer,pending=2;const events=[{date:'2026-09-14',time:'17:00',company:'青禾科技',role:'产品实习',name:'补充作品材料',status:'今天截止',detail:'按招聘邮件要求整理项目作品。截止时间为今天17:00。',action:'查看材料'},{date:'2026-09-15',time:'14:00',company:'远山智能',role:'Agent开发',name:'技术一面',status:'已确认',detail:'线上面试 · 预计45分钟。可提前复习项目经历与岗位要求。',action:'开始准备'},{date:'2026-09-18',time:'10:30',company:'星河科技',role:'Python开发实习',name:'在线笔试',status:'已确认',detail:'在线测评 · 预计60分钟。入口与要求以招聘通知为准。',action:'查看安排'},{date:'2026-09-22',time:'15:00',company:'云际数据',role:'数据分析',name:'业务面试',status:'已确认',detail:'线上业务面试 · 预计45分钟。',action:'开始准备'},{date:'2026-09-25',time:'18:00',company:'青禾科技',role:'运营实习',name:'录用条件回复',status:'截止时间',detail:'按已收到的录用通知确认回复期限。',action:'查看Offer'}];
const pad=n=>String(n).padStart(2,'0');function icons(){if(globalThis.lucide)globalThis.lucide.createIcons({attrs:{width:17,height:17}})}function toast(t){clearTimeout(toastTimer);q('.ct-toast').textContent=t;q('.ct-toast').hidden=false;toastTimer=setTimeout(()=>q('.ct-toast').hidden=true,3000)}
function renderCalendar(){q('.ct-month').textContent=year+'年'+(month+1)+'月';const cal=q('.ct-cal');cal.replaceChildren();['一','二','三','四','五','六','日'].forEach(w=>{const e=document.createElement('span');e.className='ct-week';e.textContent=w;cal.append(e)});const offset=(new Date(year,month,1).getDay()+6)%7;for(let i=0;i<42;i++){const d=new Date(year,month,i-offset+1),key=d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate()),has=events.some(e=>e.date===key),today=key==='2026-09-14';const b=document.createElement('button');b.className='ct-day'+(today?' ct-today':'')+(has?' ct-has':'')+(d.getMonth()!==month?' ct-outside':'');b.textContent=d.getDate();b.dataset.date=key;b.setAttribute('aria-pressed',String(selected===key));b.setAttribute('aria-label',`${d.getMonth()+1}月${d.getDate()}日${today?'，今天':''}${has?'，有安排':''}`);cal.append(b)}}
function renderAgenda(){const rows=selected?events.filter(e=>e.date===selected):events.slice(0,allAgenda?events.length:3);q('.ct-agenda-title').textContent=selected?Number(selected.slice(5,7))+'月'+Number(selected.slice(8))+'日的安排':'最近安排';q('.ct-agenda-caption').textContent=selected?(rows.length?rows.length+'项安排':'给这一天留一些从容'):'接下来的几件事，从容安排';q('.ct-agenda-control').textContent=selected?'返回最近安排':allAgenda?'收起':'查看全部';q('.ct-agenda').innerHTML=rows.length?rows.map(e=>`<article class="ct-agenda-item"><button class="ct-agenda-toggle" aria-expanded="false"><span class="ct-dateblock">${e.date.slice(5).replace('-','/')}<b>${e.time}</b></span><span class="ct-eventtext"><strong>${e.company} · ${e.name}</strong><small>${e.role} · ${e.status}</small></span><i data-lucide="chevron-down" aria-hidden="true"></i></button><div class="ct-agenda-detail" hidden>${e.detail}<div class="ct-actions"><button class="ct-button" data-action="event-open" data-event="${events.indexOf(e)}">${e.action}<i data-lucide="arrow-up-right" aria-hidden="true"></i></button></div></div></article>`).join(''):'<div class="ct-empty">这一天没有已知安排。<br><small>选择其他日期，或返回最近安排。</small></div>';icons()}
function resolveRequest(el,text){if(el.classList.contains('ct-removing'))return;el.querySelectorAll('button').forEach(b=>b.disabled=true);el.classList.add('ct-removing');setTimeout(()=>{el.remove();pending--;qa('.ct-pending-count').forEach(n=>n.textContent=pending);if(!pending)q('.ct-requests').innerHTML='<div class="ct-empty">都处理好了。<br><small>当前没有待确认事项。</small></div>';toast(text)},220)}
function showChat(){q('.ct-dashboard').hidden=true;q('.ct-chat').hidden=false;q('#ct-chat-input').focus({preventScroll:true})}function home(){q('.ct-chat').hidden=true;q('.ct-dashboard').hidden=false;if(q('.ct-thread').children.length)q('[data-action="resume"]').hidden=false}
function send(text){if(!text.trim())return;if(q('.ct-chat').hidden)q('.ct-thread').replaceChildren();showChat();const thread=q('.ct-thread'),bubble=document.createElement('div');bubble.className='ct-userbubble';bubble.textContent=text;thread.append(bubble);const reply=document.createElement('div');reply.className='ct-reply';const prep=/面试|准备|复习/.test(text),resume=/简历|分析/.test(text);q('.ct-context').textContent=prep?'远山智能 · Agent开发 · 一面':resume?'个人资料 · 基础简历':'Today · 当前请求';let body;if(prep){body='<p>明天14:00是远山智能的技术一面。可以从这三个方向开始准备：</p><div class="ct-result"><div class="ct-eyebrow">岗位准备 · 示例方案</div><strong>把准备落到具体内容</strong><div class="ct-resultrow"><span>01　项目讲述与个人贡献</span><small>经历</small></div><div class="ct-resultrow"><span>02　Python异步与数据库基础</span><small>基础知识</small></div><div class="ct-resultrow"><span>03　工具调用与Agent评估</span><small>岗位知识</small></div><div class="ct-actions"><button class="ct-button ct-primary" data-action="practice-preview">进入岗位准备 <i data-lucide="arrow-up-right" aria-hidden="true"></i></button></div></div><p style="margin-top:14px;color:var(--ct-muted)">你也可以直接指定想练的内容。这里只使用相关个人资料与这个岗位的材料。</p>'}else if(resume){body='<p>这份基础简历有3处表达可以更清楚。先看其中一处：</p><div class="ct-result"><div class="ct-eyebrow">简历分析 · 示例成果</div><strong>让个人贡献更具体</strong><div class="ct-inspect"><s>参与知识库问答系统开发。</s><br><ins>负责知识库问答系统的检索模块开发与效果评估。</ins></div><p style="margin-top:12px;color:var(--ct-muted)">建议补充你实际负责的模块和工作；不添加未经核实的成果数据。</p><button class="ct-button" data-action="editor-preview">查看完整修改对照</button></div>'}else{body='<p>已接住你的请求。这是Today的交互演示，尚未连接真实Agent。</p><div class="ct-result"><strong>可以继续体验</strong><div class="ct-actions" style="justify-content:flex-start"><button class="ct-button" data-prompt="帮我准备明天的面试">岗位准备示例</button><button class="ct-button" data-prompt="查看我的简历分析结果">简历分析示例</button></div></div>'}reply.innerHTML='<span class="ct-aiavatar"><i data-lucide="sparkles" aria-hidden="true"></i></span><div class="ct-replybody">'+body+'</div>';thread.append(reply);icons()}
root.addEventListener('submit',e=>{if(!e.target.matches('[data-form]'))return;e.preventDefault();const input=e.target.querySelector('textarea'),text=input.value;input.value='';input.style.height='';send(text)});qa('textarea').forEach(input=>{input.addEventListener('input',()=>{input.style.height='auto';input.style.height=Math.min(input.scrollHeight,92)+'px'});input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();input.closest('form').requestSubmit()}})});
root.addEventListener('click',e=>{const btn=e.target.closest('button');if(!btn||btn.disabled)return;if(btn.dataset.date){selected=btn.dataset.date;renderCalendar();renderAgenda();return}if(btn.dataset.prompt){send(btn.dataset.prompt);return}if(btn.classList.contains('ct-agenda-toggle')){const detail=btn.nextElementSibling;detail.hidden=!detail.hidden;btn.setAttribute('aria-expanded',String(!detail.hidden));return}switch(btn.dataset.action){case'prev':month--;if(month<0){month=11;year--}renderCalendar();break;case'next':month++;if(month>11){month=0;year++}renderCalendar();break;case'reset-date':year=2026;month=8;selected=null;renderCalendar();renderAgenda();break;case'agenda-more':if(selected){selected=null;renderCalendar()}else allAgenda=!allAgenda;renderAgenda();break;case'inspect':{const box=btn.closest('.ct-request').querySelector('.ct-inspect');box.hidden=!box.hidden;btn.textContent=box.hidden?'查看差异':'收起差异';break}case'confirm':resolveRequest(btn.closest('.ct-request'),'示例资料已修正为6月');break;case'keep':resolveRequest(btn.closest('.ct-request'),'已保留示例原记录');break;case'associate':if(!q('#ct-mail-job').value){toast('先选择这封邮件所属的岗位');q('#ct-mail-job').focus();break}resolveRequest(btn.closest('.ct-request'),'示例邮件已关联到所选岗位');break;case'home':home();break;case'resume':showChat();break;case'news-more':{const more=q('.ct-newslist .ct-more');more.hidden=!more.hidden;btn.textContent=more.hidden?'查看全部':'收起';break}case'market':{const x=btn.closest('.ct-newsbody').querySelector('.ct-inspect');x.hidden=!x.hidden;break}case'event-open':{const ev=events[Number(btn.dataset.event)];if(ev.action==='开始准备'&&ev.company==='远山智能')send('帮我准备'+ev.company+'的面试');else toast('这里将进入对应工作页面；本次先体验Today。');break}case'menu':{const menu=q('.ct-menu');menu.hidden=!menu.hidden;btn.setAttribute('aria-expanded',String(!menu.hidden));break}case'settings':toast('设置页面将在后续设计');break;case'connection':toast('示例连接状态：已连接；没有访问真实邮箱');break;case'content':toast('这里将进入面经题库的案例分析内容');break;case'practice-preview':toast('下一步进入同一岗位的练习界面；本次原型范围为Today');break;case'editor-preview':toast('下一步进入共用材料编辑器；本次原型范围为Today');break}});
let agendaMode='today',transitionTimer;
function contour(){
 if(!q('.ct-hero').clientWidth)return;
 const w=q('.ct-hero').clientWidth+64,h=260;
 const pt=(x,y)=>(w*x).toFixed(2)+' '+(h*y).toFixed(2);
 const d='M '+pt(.5,.02)+' C '+pt(.505,.12)+' '+pt(.515,.13)+' '+pt(.565,.16)+' C '+pt(.69,.22)+' '+pt(.87,.27)+' '+pt(.972,.49)+' Q '+pt(.99,.52)+' '+pt(.972,.55)+' C '+pt(.87,.74)+' '+pt(.69,.79)+' '+pt(.565,.85)+' C '+pt(.525,.87)+' '+pt(.509,.91)+' '+pt(.5,.98)+' C '+pt(.491,.91)+' '+pt(.475,.87)+' '+pt(.435,.85)+' C '+pt(.31,.79)+' '+pt(.13,.74)+' '+pt(.028,.55)+' Q '+pt(.01,.52)+' '+pt(.028,.49)+' C '+pt(.13,.27)+' '+pt(.31,.22)+' '+pt(.435,.16)+' C '+pt(.485,.13)+' '+pt(.495,.12)+' '+pt(.5,.02)+' Z';
 root.style.setProperty('--ct-contour','path("'+d+'")');
}
new ResizeObserver(contour).observe(q('.ct-hero'));contour();
q('[data-action="news-more"]').remove();
qa('.ct-newslist .ct-more').forEach(item=>{item.hidden=false;item.classList.remove('ct-more')});
const requestContainer=q('.ct-requests');
qa('.ct-request').forEach(card=>{
 const content=document.createElement('div');content.className='ct-request-content';
 while(card.firstChild)content.append(card.firstChild);
 const tab=document.createElement('button');tab.type='button';tab.className='ct-stack-tab';tab.dataset.action='stack-front';
 const summary=document.createElement('span');summary.textContent=content.querySelector('strong').textContent;
 const hint=document.createElement('small');hint.textContent='待核实 ↗';
 tab.append(summary,hint);card.append(tab,content);
});
let frontCard=q('[data-request="profile"]');
function stackLayout(){
 const cards=qa('.ct-request');
 if(!cards.includes(frontCard))frontCard=cards[0];
 cards.forEach(card=>{const front=card===frontCard;card.classList.toggle('ct-back',!front);card.querySelector('.ct-stack-tab').hidden=front;card.querySelector('.ct-request-content').hidden=!front;card.querySelector('.ct-stack-tab').setAttribute('aria-expanded',String(front));card.style.top=front?(cards.length>1?'38px':'0px'):'0px'});
}
stackLayout();
const todayTotal=document.createElement('span');todayTotal.className='ct-today-total';todayTotal.textContent='今天 '+events.filter(e=>e.date==='2026-09-14').length+' 项';q('.ct-legend').insertBefore(todayTotal,q('[data-action="reset-date"]'));
const tabs=document.createElement('div');tabs.className='ct-tabs';tabs.setAttribute('aria-label','安排时间范围');
['今天','近期'].forEach((label,i)=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.dataset.agenda=i?'recent':'today';b.setAttribute('aria-pressed',String(!i));tabs.append(b)});
q('.ct-agenda-control').parentElement.append(tabs);
renderAgenda=function(){
 const rows=selected?events.filter(e=>e.date===selected):agendaMode==='today'?events.filter(e=>e.date==='2026-09-14'):events.slice(0,3);
 const dateLabel=d=>d==='2026-09-14'?'今天 · 9月14日':d==='2026-09-15'?'明天 · 9月15日':Number(d.slice(5,7))+'月'+Number(d.slice(8))+'日';
 q('.ct-agenda-title').textContent=selected?Number(selected.slice(5,7))+'月'+Number(selected.slice(8))+'日的安排':agendaMode==='today'?'今天的安排':'近期安排';
 q('.ct-agenda-caption').textContent=selected?rows.length+'项安排 · 日历所选日期':agendaMode==='today'?'9月14日 · 星期一 · '+rows.length+'项安排':'今天起7天内 · 按日期排列';
 qa('[data-agenda]').forEach(b=>b.setAttribute('aria-pressed',String(!selected&&agendaMode===b.dataset.agenda)));
 const container=q('.ct-agenda');container.replaceChildren();
 let lastDate='';
 rows.forEach(e=>{
  if(!selected&&agendaMode==='recent'&&lastDate!==e.date){const group=document.createElement('div');group.className='ct-daygroup';group.textContent=dateLabel(e.date);container.append(group);lastDate=e.date}
  const article=document.createElement('article');article.className='ct-agenda-item';
  const button=document.createElement('button');button.className='ct-agenda-toggle';button.setAttribute('aria-expanded','false');
  const time=document.createElement('span');time.className='ct-dateblock';const timeValue=document.createElement('b');timeValue.textContent=e.time;time.append(timeValue);
  const txt=document.createElement('span');txt.className='ct-eventtext';const title=document.createElement('strong');title.textContent=e.company+' · '+e.name;const sub=document.createElement('small');sub.textContent=e.role+' · '+e.status;txt.append(title,sub);
  const arrow=document.createElement('i');arrow.dataset.lucide='chevron-down';button.append(time,txt,arrow);
  const detail=document.createElement('div');detail.className='ct-agenda-detail';detail.hidden=true;detail.textContent=e.detail;
  const actions=document.createElement('div');actions.className='ct-actions';const action=document.createElement('button');action.className='ct-button';action.dataset.action='event-open';action.dataset.event=events.indexOf(e);action.textContent=e.action;actions.append(action);detail.append(actions);article.append(button,detail);container.append(article);
 });
 if(!rows.length){const empty=document.createElement('div');empty.className='ct-empty';empty.textContent='这一天没有已知安排。';container.append(empty)}
 if(!selected&&agendaMode==='today'){const footer=document.createElement('div');footer.className='ct-day-footer';footer.textContent='仅显示今天。切换「近期」可提前查看后续安排。';container.append(footer)}
 icons();
};
const originalResolve=resolveRequest;
resolveRequest=function(el,text){originalResolve(el,text);setTimeout(stackLayout,230)};
showChat=function(){
 if(!q('.ct-chat').hidden)return;
 const main=q('.ct-main'),hero=q('.ct-hero'),rect=hero.getBoundingClientRect(),base=main.getBoundingClientRect();
 const layer=document.createElement('div');layer.className='ct-star-transition';layer.style.left=(rect.left-base.left-32)+'px';layer.style.top=(rect.top-base.top-16)+'px';layer.style.width=(rect.width+64)+'px';layer.style.height=(rect.height+32)+'px';main.append(layer);
 const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
 requestAnimationFrame(()=>requestAnimationFrame(()=>layer.classList.add('ct-expanded')));
 q('.ct-dashboard').inert=true;
 transitionTimer=setTimeout(()=>{q('.ct-dashboard').hidden=true;q('.ct-dashboard').inert=false;q('.ct-chat').hidden=false;layer.classList.add('ct-fading');q('#ct-chat-input').focus({preventScroll:true});setTimeout(()=>layer.remove(),320)},reduced?0:740);
};
const originalHome=home;
home=function(){clearTimeout(transitionTimer);qa('.ct-star-transition').forEach(e=>e.remove());q('.ct-dashboard').inert=false;originalHome();stackLayout()};
root.addEventListener('click',e=>{const button=e.target.closest('button');if(!button)return;if(button.dataset.action==='stack-front'){frontCard=button.closest('.ct-request');stackLayout()}if(button.dataset.agenda){agendaMode=button.dataset.agenda;selected=null;renderCalendar();renderAgenda()}if(button.dataset.action==='reset-date'){agendaMode='today';renderAgenda()}});
renderAgenda();
root.addEventListener('click',e=>{const b=e.target.closest('[data-action="inspect"]');if(b){const card=b.closest('.ct-request');card.classList.toggle('ct-detail-open',!card.querySelector('.ct-inspect').hidden);b.setAttribute('aria-expanded',String(!card.querySelector('.ct-inspect').hidden))}});

const orbitGroup=document.createElement('div');orbitGroup.className='ct-orbits';orbitGroup.setAttribute('aria-hidden','true');
for(let i=0;i<8;i++){const item=document.createElement('span');item.className=i<3?'ct-orbit':'ct-orbit-dot';orbitGroup.append(item)}
q('.ct-hero').prepend(orbitGroup);

renderCalendar();renderAgenda();if(globalThis.Tweak){const opts={softness:100,gap:32};new Tweak({container:root,onChange:()=>{q('.ct-dashboard').style.columnGap=opts.gap+'px';q('.ct-main').style.backgroundSize=opts.softness+'% '+opts.softness+'%'}}).addSlider(opts,'gap',{label:'四区横向间距',min:20,max:48,unit:'px'});}
})();
