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
