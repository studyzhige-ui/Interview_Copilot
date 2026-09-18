"""Product-side, anonymous browser reader for Tencent campus job details."""
import re, threading
from datetime import datetime, timezone
from urllib.parse import urlsplit, parse_qs

SLOTS=threading.BoundedSemaphore(2)
def job_id(url):
    u=urlsplit(url)
    ids=parse_qs(u.query).get('postid',[])
    if u.scheme!='https' or u.netloc!='join.qq.com' or u.path!='/post_detail.html' or len(ids)!=1 or not re.fullmatch(r'\d{1,30}',ids[0]):
        raise ValueError('请粘贴具体岗位详情链接，而不是岗位列表或个人申请页面。')
    return ids[0]

def parse_rendered(data,url):
    title=data.get('title','').strip();sections=[]
    for block in data.get('blocks',[]):
        lines=block.strip().split('\n',1)
        if len(lines)==2 and lines[0] in ['岗位描述','岗位要求','加分项或注意事项']:
            sections.append({'title':lines[0],'text':lines[1].strip()})
    if not title or len(title)>180 or any(not any(s['title']==name and len(s['text'])>=20 for s in sections) for name in ['岗位描述','岗位要求']):
        raise ValueError('页面已打开，但岗位内容不完整。岗位可能已下线，请在官网核对。')
    tags=data.get('tags',[])
    return {'company':'腾讯','title':title,'jobId':job_id(url),'url':url,'category':tags[0] if tags else '',
            'audience':tags[1] if len(tags)>1 else '', 'captureMethod':'浏览器解析',
            'capturedOn':datetime.now(timezone.utc).isoformat(),'sections':sections}

def read_tencent(url):
    expected=job_id(url)
    try:from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout
    except ImportError:raise ValueError('浏览器读取依赖尚未安装，请安装 requirements-jobs.txt。')
    if not SLOTS.acquire(blocking=False):raise ValueError('正在读取其他岗位，请稍后重试。')
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True,timeout=15000)
            try:
                context=browser.new_context(locale='zh-CN',service_workers='block',accept_downloads=False)
                def route(request_route):
                    req=request_route.request;u=urlsplit(req.url);host=u.hostname or ''
                    allowed=u.scheme=='https' and (host=='cdn.multilingualres.hr.tencent.com' or any(host==d or host.endswith('.'+d) for d in ['qq.com','gtimg.com','qpic.cn','idqqimg.com']))
                    if not allowed or req.resource_type in ['image','media','font']:request_route.abort()
                    else:request_route.continue_()
                context.route('**/*',route)
                page=context.new_page()
                page.goto(url,wait_until='domcontentloaded',timeout=20000)
                page.locator('.bannerItemText').filter(has_text=re.compile(r'\S')).wait_for(state='visible',timeout=20000)
                page.locator('.detail_box').filter(has_text='岗位要求').wait_for(state='visible',timeout=10000)
                if job_id(page.url)!=expected:raise ValueError('页面跳转到其他岗位，未保存解析结果。')
                data={'title':page.locator('.bannerItemText').inner_text(),
                      'blocks':page.locator('.detail_box').all_inner_texts(),
                      'tags':page.locator('.bannerTag').all_inner_texts()}
                return parse_rendered(data,url)
            finally:browser.close()
    except ValueError:raise
    except BrowserTimeout:raise ValueError('官网加载超时或需要验证，请在浏览器打开原页检查后重试。')
    except Exception:raise ValueError('浏览器暂时无法读取此岗位，请确认 Chrome 可用后重试。')
    finally:SLOTS.release()
