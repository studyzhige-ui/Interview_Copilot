"""Bounded public-page parser. No authentication, browser simulation, or cached JD fallback."""
import json
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from bs4 import BeautifulSoup

HOSTS={'join.qq.com','app.mokahr.com','cicdi2027.zhaopin.com','sgssemi.zhiye.com','orienspace.zhiye.com'}
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def validate_url(url):
    u=urlsplit(url)
    if u.scheme!='https' or u.hostname not in HOSTS or u.username or u.password or u.port not in (None,443):
        raise ValueError('此网站暂未支持自动解析，请切换手动填写。')
    return url

def parse_html(html,url):
    soup=BeautifulSoup(html,'html.parser')
    def walk(value):
        if isinstance(value,list):
            for x in value:yield from walk(x)
        elif isinstance(value,dict):
            types=value.get('@type',[])
            if types=='JobPosting' or isinstance(types,list) and 'JobPosting' in types:yield value
            for x in value.values():
                if isinstance(x,(list,dict)):yield from walk(x)
    found=[]
    for script in soup.find_all('script',type='application/ld+json'):
        try:found.extend(walk(json.loads(script.string or script.get_text())))
        except (ValueError,TypeError):continue
    if len(found)!=1:raise ValueError('未能从这个页面读取完整岗位信息。页面可能需要登录或动态加载，请切换手动填写。')
    j=found[0];title=j.get('title');org=j.get('hiringOrganization',{})
    company=org.get('name') if isinstance(org,dict) else None
    description=BeautifulSoup(str(j.get('description','')),'html.parser').get_text('\n',strip=True)
    if not isinstance(title,str) or not isinstance(company,str) or len(description)<20:raise ValueError('岗位字段不完整，请切换手动填写。')
    return {'company':company[:100],'title':title[:180],'url':url,'category':'','audience':'','jobId':'','captureMethod':'链接解析','capturedOn':datetime.now(timezone.utc).isoformat(),'sections':[{'title':'职位描述与要求','text':description[:60000]}]}

def parse_job(url):
    url=validate_url(url)
    if urlsplit(url).hostname=='join.qq.com':
        from job_browser import read_tencent
        return read_tencent(url)
    try:
        with build_opener(NoRedirect).open(Request(url,headers={'User-Agent':'CareerOS-Prototype/0.1','Accept':'text/html'}),timeout=12) as response:
            raw=response.read(2_000_001)
            if len(raw)>2_000_000:raise ValueError('页面过大，请切换手动填写。')
            html=raw.decode(response.headers.get_content_charset() or 'utf-8',errors='replace')
    except ValueError:raise
    except Exception:raise ValueError('暂时无法读取官网，请稍后重试或切换手动填写。')
    return parse_html(html,url)
