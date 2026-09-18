from pathlib import Path
import re

p=Path(r'C:/Users/Alice/.codex/visualizations/2026/09/14/01a09ebf-2073-7412-962b-9e3cb7227a1f')
f=p/'profile-v2.js'
s=f.read_text(encoding='utf-8')
start=s.index('function resume(){')
end=s.index('\n',start)
s=s[:start]+'''function resume(){if(editing){toast('请先保存当前资料，再制作简历');return}try{localStorage.setItem('career-profile-records-v1',JSON.stringify({records,active:[...active]}));sessionStorage.setItem('career-resume-seed',JSON.stringify({records,active:[...active]}));window.location.href='/editor/index.html'}catch{toast('浏览器存储不可用，请在 Chrome 打开本地页面')}}'''+s[end:]
if "function persistProfile()" not in s:
    needle='function render(){'
    insert="""function persistProfile(){try{localStorage.setItem('career-profile-records-v1',JSON.stringify({records,active:[...active]}))}catch{}}
try{const saved=JSON.parse(localStorage.getItem('career-profile-records-v1')||'null');if(saved?.records){for(const d of defs)if(Array.isArray(saved.records[d.id]))records[d.id]=saved.records[d.id];active.clear();(saved.active||defs.filter(d=>!d.optional).map(d=>d.id)).forEach(k=>active.add(k))}}catch{}
"""
    s=s.replace(needle,insert+needle+'persistProfile();',1)
f.write_text(s,encoding='utf-8')
exec((p/'build-profile-v2.py').read_text(encoding='utf-8'),{'__file__':str(p/'build-profile-v2.py')})
exec((p/'export-profile-chrome.py').read_text(encoding='utf-8'),{'__file__':str(p/'export-profile-chrome.py')})
