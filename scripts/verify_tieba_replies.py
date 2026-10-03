"""Actual Chrome, wholly intercepted Tieba fixture; never sends to the platform."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from jm_workbench.adapters.chrome import endpoint
from jm_workbench.community.adapters import tieba_reply_and_submit,NotSubmitted

HTML='''<div class="pc-main-page-layout"></div><div class="pc-pb-reply-box"><div id="tb-editor-pb-content"><div class="ql-editor" contenteditable="true"></div></div><button class="publish-btn">发布</button></div>
<script>document.querySelector('.pc-main-page-layout').__vue__={$pinia:{state:{value:{userStore:{isLogin:true,user:{user_id:'test-user'}}}}}};
document.querySelector('button').onclick=()=>{const body=JSON.stringify({tid:'123456',quote_id:'',content:document.querySelector('.ql-editor').innerText});for(let i=0;i<2;i++)fetch('/c/c/post/add_pc',{method:'POST',body}).catch(()=>{});};</script>'''

def main():
    checks=[]
    with sync_playwright() as pw:
        b=pw.chromium.connect_over_cdp(endpoint(Path(r'D:\Codex\个人工作台\项目\Codex-Chrome\User Data')))
        c=b.contexts[0];original=list(c.pages);p=c.new_page();calls=[]
        def fixture(route):
            if '/c/c/post/add_pc' in route.request.url:
                calls.append(route.request.post_data);route.fulfill(json={'errno':0,'data':{'pid':'987654'}})
            else:route.fulfill(content_type='text/html',body=HTML)
        p.route('**/*',fixture)
        try:
            p.goto('https://tieba.baidu.com/p/123456')
            result=tieba_reply_and_submit(p,{'body':'这是只存在于本机夹具的验收评论'},'test-user',p.url)
            p.wait_for_timeout(200)
            assert len(calls)==1 and result['comment_id']=='987654';checks.append('one click one network write despite site retry')
            assert '验收评论' in json.loads(calls[0])['content'];checks.append('exact comment body captured')
            for identity,target,body in [('changed','https://tieba.baidu.com/p/123456',''),('test-user','https://tieba.baidu.com/p/222222',''),('test-user','https://tieba.baidu.com/p/123456','unsaved')]:
                p.goto('https://tieba.baidu.com/p/123456');p.locator('.ql-editor').fill(body)
                try:tieba_reply_and_submit(p,{'body':'不会发布'},identity,target)
                except NotSubmitted:pass
                else:raise AssertionError('preflight should reject')
            assert len(calls)==1;checks.append('identity target and existing draft block submission')
        finally:p.close()
        assert all(not p.is_closed() for p in original);checks.append('original browser pages preserved')
    print(json.dumps({'checks':checks,'real_sends':0},ensure_ascii=False))

if __name__=='__main__':main()
