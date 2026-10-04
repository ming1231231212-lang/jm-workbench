"""Isolated native-form contract checks; all network responses are local fixtures."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from jm_workbench.adapters.chrome import endpoint
from jm_workbench.community.csdn import identity, prepare_reply, SubmitGuard, receipt
from jm_workbench.community.adapters import PreflightStopped


def main():
    target='https://blog.csdn.net/source_author/article/details/123456789'
    payload={'kind':'reply','title':'测试','body':'AI辅助整理：保持输入和验收条件相同，检查每个输出字段是否有原始材料支持。','source_title':'测试原文','source_excerpt':'原文讨论资料整理的验收条件，保留不确定的信息。'}
    fixture='''<!doctype html><meta charset="utf-8"><meta property="article:published_time" content="2026-10-04T10:00:00+08:00"><meta name="keywords" content="人工智能">
<div id="csdn-toolbar"><a class="hasAvatar" href="https://blog.csdn.net/test_author">本人</a></div>
<h1>测试原文</h1><div id="content_views">原文讨论资料整理的验收条件，保留不确定的信息。</div>
<a href="https://blog.csdn.net/source_author">文章作者</a><div id="toolBarBox"><a class="go-side-comment">评论</a></div>
<textarea id="comment_content"></textarea><input id="comment_replyId" value=""><input class="btn-comment-input" type="button" onclick="send()" value="评论">
<script>window.articleId=123456789;window.username='source_author';function send(){fetch('/phoenix/web/v1/comment/submit',{method:'POST',body:new URLSearchParams({articleId:'123456789',commentId:'',content:document.querySelector('textarea').value})})}</script>'''
    checks=[];requests=[]
    with sync_playwright() as pw:
        b=pw.chromium.connect_over_cdp(endpoint(Path(r'D:\Codex\个人工作台\项目\Codex-Chrome\User Data')));c=b.new_context()
        def route(r):
            if '/comment/submit' in r.request.url:
                requests.append(r.request.post_data);return r.fulfill(status=200,content_type='application/json',body=json.dumps({'code':200,'data':23456789}))
            if r.request.url==target:return r.fulfill(status=200,content_type='text/html',body=fixture)
            return r.abort('blockedbyclient')
        c.route('**/*',route)
        try:
            p=c.new_page();p.goto(target);assert identity(p)=='test_author';checks.append('own toolbar identity distinct from article author')
            button=prepare_reply(p,payload,'test_author',target);g=SubmitGuard(payload,target);g.armed=True;p.route('**/comment/submit*',g.route)
            with p.expect_response(lambda r:'/comment/submit' in r.url) as response:button.click()
            assert receipt(response.value.json(),'reply',target,'test_author')['comment_id']=='23456789';assert len(requests)==1;checks.append('native form single request and explicit receipt')
            p.evaluate('send()');p.wait_for_timeout(100);assert len(requests)==1;checks.append('duplicate native request blocked')
            p.close();p=c.new_page();p.goto(target);p.locator('#content_views').evaluate('(e)=>e.textContent="changed source"')
            try:prepare_reply(p,payload,'test_author',target);raise AssertionError('source changed')
            except PreflightStopped:pass
            checks.append('changed original rejected before submit')
            p.close();p=c.new_page();p.goto(target);p.locator('#comment_replyId').fill('12345')
            try:prepare_reply(p,payload,'test_author',target);raise AssertionError('nested reply accepted')
            except PreflightStopped:pass
            checks.append('nested reply editor rejected')
            p.locator('#comment_replyId').fill('');p.locator('#comment_content').fill('existing user draft')
            try:prepare_reply(p,payload,'test_author',target);raise AssertionError('draft overwritten')
            except PreflightStopped:pass
            assert p.locator('#comment_content').input_value()=='existing user draft';checks.append('different unsent draft preserved')
            p.locator('#comment_content').fill('');p.locator('#csdn-toolbar a').evaluate('(e)=>e.href="https://blog.csdn.net/other_author"')
            try:prepare_reply(p,payload,'test_author',target);raise AssertionError('identity changed')
            except PreflightStopped:pass
            assert len(requests)==1;checks.append('identity change stops before request')
        finally:c.close()
    print(json.dumps({'checks':checks,'real_sends':0},ensure_ascii=False))


if __name__=='__main__':main()
