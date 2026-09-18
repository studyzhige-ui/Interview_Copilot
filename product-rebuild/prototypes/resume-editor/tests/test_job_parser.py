import sys, json, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from job_parser import parse_html, validate_url
from job_browser import parse_rendered, job_id

class JobParserTests(unittest.TestCase):
    def test_extracts_one_job_from_graph(self):
        obj={'@graph':[{'@type':'Organization','name':'Other'},{'@type':'JobPosting','title':'测试岗位','hiringOrganization':{'name':'测试公司'},'description':'<p>负责测试岗位系统设计与开发，并编写完整的自动化验证方案。</p>'}]}
        j=parse_html('<script type="application/ld+json">'+json.dumps(obj)+'</script>','https://join.qq.com/post_detail.html?postid=1')
        self.assertEqual(j['company'],'测试公司');self.assertEqual(j['title'],'测试岗位');self.assertNotIn('<p>',j['sections'][0]['text'])
    def test_never_falls_back_to_sample(self):
        with self.assertRaises(ValueError):parse_html('<div id="app"></div>','https://join.qq.com/post_detail.html?postid=123')
    def test_rejects_non_public_or_unapproved_targets(self):
        for url in ['http://127.0.0.1/','https://localhost/','https://join.qq.com:8443/','https://join.qq.com.evil.test/','https://name:secret@join.qq.com/']:
            with self.assertRaises(ValueError):validate_url(url)
    def test_job_list_is_not_one_job(self):
        obj=[{'@type':'JobPosting','title':str(n)} for n in range(2)]
        with self.assertRaises(ValueError):parse_html('<script type="application/ld+json">'+json.dumps(obj)+'</script>','https://join.qq.com/post.html')
    def test_rendered_job_retains_identity_and_sections(self):
        url='https://join.qq.com/post_detail.html?postid=1282707398326592512'
        data={'title':'AI全栈工程师','tags':['技术','应届毕业生'],'blocks':['岗位描述\n负责产品业务系统的全栈开发，涵盖前端交互、后端服务、数据存储等。','岗位要求\n熟练掌握主流前后端技术栈，具备扎实的计算机基础知识和全栈工程能力。']}
        j=parse_rendered(data,url)
        self.assertEqual(j['jobId'],'1282707398326592512');self.assertEqual(j['title'],'AI全栈工程师');self.assertEqual(len(j['sections']),2)
        self.assertEqual(j['audience'],'应届毕业生')
    def test_rendered_incomplete_job_is_not_saved(self):
        with self.assertRaises(ValueError):parse_rendered({'title':'未加载','blocks':[]},'https://join.qq.com/post_detail.html?postid=1')
    def test_only_one_detail_identity(self):
        for url in ['https://join.qq.com/post.html','https://join.qq.com/post_detail.html?postid=1&postid=2']:
            with self.assertRaises(ValueError):job_id(url)

if __name__=='__main__':unittest.main()
