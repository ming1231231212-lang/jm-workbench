"""Browser contract checks; every website/API response is a local fixture."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from jm_workbench.adapters.chrome import endpoint
from jm_workbench.community.juejin import prepare_reply, submit_once, identity
from jm_workbench.community.adapters import PreflightStopped, NotSubmitted


def main():
    target='https://juejin.cn/post/1234567890123456'
    payload={'kind':'reply','title':'测试评论','body':'AI辅助整理：建议记录原始样本与输出，再核对字段与来源，不将未知信息补成确定值。',
             'source_title':'原帖标题','source_excerpt':'原帖正文包含一个可复现的问题。'}
    fixture='''<!doctype html><html><meta charset="utf-8"><header><div class="avatar-wrapper">账号</div><div class="nav-item menu"><a href="/user/12345">我的主页</a></div></header>
<article><h1 class="article-title">原帖标题</h1><div class="author-info-block"><a href="/user/99999/posts">作者</a></div>
<time datetime="2026-10-04T00:00:00Z"></time><div id="article-root">原帖正文包含一个可复现的问题。</div></article>
<div class="auth-card"><div class="rich-input" contenteditable="true"></div><button class="submit-btn" onclick="send()">发送</button></div>
<script>function send(){fetch('https://api.juejin.cn/interact_api/v1/comment/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item_id:'1234567890123456',item_type:2,comment_content:document.querySelector('.rich-input').innerText,comment_pics:[]})})}</script></html>'''
    checks=[];requests=[];response={'err_no':0,'data':{'comment_info':{'comment_id':'2345678901234567','item_id':'1234567890123456'}}}
    with sync_playwright() as pw:
        b=pw.chromium.connect_over_cdp(endpoint(Path(r'D:\Codex\个人工作台\项目\Codex-Chrome\User Data')),timeout=10000)
        c=b.new_context()
        def route(r):
            if 'api.juejin.cn/' in r.request.url:
                if r.request.method=='OPTIONS':return r.fulfill(status=204,headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'content-type'})
                requests.append(r.request.post_data_json)
                return r.fulfill(status=200,content_type='application/json',headers={'Access-Control-Allow-Origin':'*'},body=json.dumps(response))
            if r.request.url==target:return r.fulfill(status=200,content_type='text/html',body=fixture)
            return r.abort('blockedbyclient')
        c.route('**/*',route)
        try:
            p=c.new_page();p.goto(target)
            assert identity(p)=='12345';checks.append('identity limited to own header profile')
            button=prepare_reply(p,payload,'12345',target)
            result=submit_once(p,button,payload,target)
            assert result['comment_id']=='2345678901234567' and len(requests)==1
            checks.append('exact top-level reply body target and receipt')
            p.evaluate('send()');p.wait_for_timeout(200)
            assert len(requests)==1;checks.append('site repeated POST blocked after first request')
            p.close();p=c.new_page();p.goto(target)
            p.locator('#article-root').evaluate('(x)=>x.textContent="原文已改变"')
            try:prepare_reply(p,payload,'12345',target);raise AssertionError('changed content accepted')
            except PreflightStopped:pass
            assert len(requests)==1;checks.append('changed original source stopped before submit')
            p.close();p=c.new_page();p.goto(target)
            p.locator('header a').evaluate('(x)=>x.href="/user/77777"')
            try:prepare_reply(p,payload,'12345',target);raise AssertionError('identity change accepted')
            except PreflightStopped:pass
            assert len(requests)==1;checks.append('changed identity stopped before submit')
            p.close();p=c.new_page();p.goto(target)
            response.clear();response.update(err_no=1)
            button=prepare_reply(p,payload,'12345',target)
            try:submit_once(p,button,payload,target);raise AssertionError('rejection accepted')
            except NotSubmitted:pass
            assert len(requests)==2;checks.append('explicit rejection is not success')
            p.close();p=c.new_page();p.goto(target)
            response.clear();response.update(err_no=0,data={})
            button=prepare_reply(p,payload,'12345',target)
            try:submit_once(p,button,payload,target);raise AssertionError('missing receipt accepted')
            except RuntimeError:pass
            assert len(requests)==3;checks.append('unknown receipt sends once only')
        finally:c.close()
    print(json.dumps({'checks':checks,'real_sends':0},ensure_ascii=False))


if __name__=='__main__':main()
