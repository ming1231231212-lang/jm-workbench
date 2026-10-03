"""Chrome acceptance against an isolated DB, fake adapters and network fixtures."""
import json
import socket
import threading
import time
from pathlib import Path
import uvicorn
from playwright.sync_api import sync_playwright, expect
from jm_workbench.web.app import create_app
from jm_workbench.adapters.chrome import endpoint
from jm_workbench.community.adapters import tieba_fill_and_submit, tieba_identity, tieba_existing_identity, NotSubmitted
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]


def main():
    output=ROOT/'outputs'/('community-acceptance-'+time.strftime('%Y%m%d-%H%M%S'));output.mkdir(parents=True)
    class Fake:
        sent=[]
        failure=False
        logged_in=False
        def check(self,a,secret):
            if not self.logged_in:raise NotSubmitted('等待贴吧登录')
            return '123'
        def publish(self,a,secret,payload,target):
            self.sent.append((payload['title'],target))
            if self.failure:raise TimeoutError()
            return {'post_id':'123456','url':'https://tieba.baidu.com/p/123456','visibility':'unverified'}
        def open(self,a,url):return {'message':'模拟打开账号浏览器'}
    fake=Fake();app=create_app(output/'home',worker=False,community_adapter=fake)
    s=app.state.community
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(16);port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='warning'))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    checks=[];errors=[]
    def check(name,condition=True):
        assert condition,name
        checks.append(name)
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp(endpoint(Path(r'D:\Codex\个人工作台\项目\Codex-Chrome\User Data')),timeout=15000)
        context=browser.contexts[0];original=list(context.pages)
        page=context.new_page();page.set_viewport_size({'width':1440,'height':980});page.set_default_timeout(10000)
        page.clock.install()
        page.on('pageerror',lambda error:errors.append(str(error)))
        fixture=None
        def refresh():
            page.locator('[data-action="refresh"]').click()
            expect(page.locator('#toast')).to_contain_text('数据已刷新')
        try:
            page.goto(f'http://127.0.0.1:{port}/#community')
            expect(page.locator('#content h1')).to_have_text('社区发布')
            check('six main routes',page.locator('#nav a').count()==6)
            page.locator('[data-action="com-new-account"]').click()
            expect(page.locator('[name="platform"]')).to_have_value('tieba')
            expect(page.locator('.com-api-secret')).not_to_be_visible()
            page.locator('[name="name"]').fill('贴吧验收账号')
            page.locator('#com-account-form button.primary').click()
            expect(page.locator('#dialog')).not_to_be_visible()
            expect(page.locator('#content')).to_contain_text('贴吧验收账号')
            check('account saved; no send',not fake.sent)
            expect(page.locator('#content')).to_contain_text('等待贴吧登录')
            fake.logged_in=True
            page.clock.fast_forward(31000)
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            expect(page.locator('#content')).to_contain_text('已登录 · 已同步')
            check('return to workbench automatically syncs login without publishing',not fake.sent)
            page.locator('[data-action="com-check"]').click()
            expect(page.locator('#toast')).to_contain_text('账号身份已核验')
            expect(page.locator('[data-action="com-check"]')).to_be_enabled()
            check('identity check')
            kept_account=s.state()['accounts'][0]['id']
            page.locator('[data-action="com-new-account"]').click()
            page.locator('[name="name"]').fill('贴吧验收账号')
            page.locator('[name="identity_hint"]').fill('多余记录（删除验收）')
            page.locator('#com-account-form button.primary').click()
            expect(page.locator('#dialog')).not_to_be_visible()
            expect(page.locator('#content tbody tr')).to_have_count(2)
            check('same-name accounts remain separately addressable',len(s.state()['accounts'])==2)
            duplicate=page.locator('#content tbody tr').filter(has_text='多余记录（删除验收）')
            duplicate.locator('[data-action="com-delete-account"]').click()
            expect(page.locator('#com-delete-account-form')).to_contain_text('多余记录（删除验收）')
            page.locator('#com-delete-account-form button').filter(has_text='取消').click()
            expect(page.locator('#dialog')).not_to_be_visible()
            check('cancel deletion keeps both accounts',len(s.state()['accounts'])==2)
            duplicate.locator('[data-action="com-delete-account"]').click()
            page.locator('#com-delete-account-form button').filter(has_text='确认删除').click()
            expect(page.locator('#dialog')).not_to_be_visible()
            expect(page.locator('#content tbody tr')).to_have_count(1)
            check('deletion preserves the other same-name logged-in account',s.state()['accounts'][0]['id']==kept_account and s.account(kept_account)['identity']=='123' and not fake.sent)
            page.locator('[data-action="com-new"]').click()
            page.locator('[name="title"]').fill('浏览器验收文字主题帖')
            page.locator('[name="body"]').fill('这是本地模拟验收正文，不会发送到真实贴吧。')
            page.locator('[name="account_ids"]').check()
            page.locator('[name^="destination_"]').fill('人工智能')
            page.locator('[name="submit_mode"][value="draft"]').click()
            expect(page.locator('#dialog')).not_to_be_visible()
            expect(page.locator('.community-post')).to_contain_text('本地草稿')
            page.reload();expect(page.locator('.community-post')).to_contain_text('浏览器验收文字主题帖')
            check('draft persistence and no send',not fake.sent)
            page.locator('[data-action="com-edit"]').click()
            expect(page.locator('[name^="destination_"]')).to_have_value('人工智能')
            page.locator('[name="submit_mode"][value="launch"]').click()
            expect(page.locator('#dialog')).not_to_be_visible()
            expect(page.locator('.community-jobs')).to_contain_text('等待执行')
            check('queue created without worker',not fake.sent)
            page.locator('[data-action="com-pause"]').click()
            expect(page.locator('.community-jobs')).to_contain_text('已暂停')
            s.tick();check('pause stops publisher',not fake.sent)
            page.locator('[data-action="com-resume"]').click()
            expect(page.locator('.community-jobs')).to_contain_text('等待执行')
            s.tick();refresh()
            expect(page.locator('.community-jobs')).to_contain_text('已提交 · 未核验')
            check('one mock send with exact board',fake.sent==[('浏览器验收文字主题帖','人工智能')])
            page.locator('[data-action="com-tab"][data-id="accounts"]').click()
            page.locator('[data-action="com-delete-account"]').click()
            page.locator('#com-delete-account-form button').filter(has_text='确认删除').click()
            expect(page.locator('#toast')).to_contain_text('停用')
            expect(page.locator('#dialog')).to_be_visible()
            expect(page.locator('#com-delete-account-form button.danger')).to_be_enabled()
            check('referenced account deletion blocked with history preserved',len(s.state()['accounts'])==1 and len(s.state()['posts'][0]['jobs'])==1)
            page.locator('#com-delete-account-form button').filter(has_text='取消').click()
            page.locator('[data-action="com-tab"][data-id="posts"]').click()
            page.locator('[data-action="com-view"]').click()
            expect(page.locator('#com-copy-body')).to_have_value('这是本地模拟验收正文，不会发送到真实贴吧。')
            page.locator('[data-action="close-dialog"]').click()
            check('content review available')
            page.locator('[data-action="com-tab"][data-id="platforms"]').click()
            expect(page.locator('#content tbody tr')).to_have_count(20)
            page.locator('[name="region"]').select_option('国外')
            page.locator('#com-filter button').click()
            expect(page.locator('#content tbody tr')).to_have_count(10)
            check('20 platforms, region filtering')
            page.locator('[name="query"]').fill('Hacker News')
            page.locator('#com-filter button').click()
            expect(page.locator('#content tbody tr')).to_have_count(1)
            expect(page.locator('#content tbody')).to_contain_text('仅本人网页发布')
            check('manual platform capability is explicit')
            page.locator('[data-action="com-tab"][data-id="posts"]').click()
            page.screenshot(path=str(output/'community-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            for tab in ('posts','accounts','platforms'):
                page.locator(f'[data-action="com-tab"][data-id="{tab}"]').click()
                check('mobile no body overflow '+tab,page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'))
            page.screenshot(path=str(output/'community-mobile.png'),full_page=True)
            check('no browser runtime errors',not errors)

            # Entire fixture page traffic is intercepted, including the write.
            # This tests the actual editor adapter with browser events, without live posting.
            fixture=context.new_page();calls=[]
            html='''<div class="pc-main-page-layout"></div><div id="tb-editor-title"><div class="ql-editor" contenteditable="true"></div></div><div id="tb-editor-content"><div class="ql-editor" contenteditable="true"></div></div><div class="footer-safe-issue"><button class="issue-btn" onclick="fetch('/c/c/thread/add_pc',{method:'POST',body:'test'}).then(()=>fetch('/c/c/thread/add_pc',{method:'POST',body:'duplicate'}))">发布</button></div><script>document.querySelector('.pc-main-page-layout').__vue__={$pinia:{state:{value:{userStore:{isLogin:true,user:{user_id:'123',name:''}},publishStore:{selectedForum:{name:'人工智能'}}}}}};</script>'''
            def route(r):
                if '/c/c/thread/add_pc' in r.request.url:
                    calls.append(r.request.post_data)
                    r.fulfill(status=200,content_type='application/json',body=json.dumps({'error_code':0,'data':{'tid':'456789'}}))
                elif r.request.resource_type=='document':r.fulfill(status=200,content_type='text/html; charset=utf-8',body=html)
                else:r.abort()
            fixture.route('**/*',route)
            fixture.goto('https://tieba.baidu.com/f?kw=test')
            check('empty nickname is a valid logged-in identity',tieba_identity(fixture)=='123')
            fixture.evaluate("document.querySelector('.pc-main-page-layout').__vue__.$pinia.state.value.userStore.user.name='renamed'")
            check('nickname change preserves stable identity',tieba_identity(fixture)=='123')
            check('existing-page sync is read-only',tieba_existing_identity(SimpleNamespace(pages=[fixture]))=='123' and not calls)
            fixture.evaluate("document.querySelector('.pc-main-page-layout').__vue__.$pinia.state.value.userStore.isLogin=false;window.PageData={user:{is_login:1,user_id:'123',user_name:'stale'}}")
            try:tieba_identity(fixture)
            except NotSubmitted:pass
            else:raise AssertionError('logged-out Pinia accepted stale legacy identity')
            check('logout rejects stale user and legacy state',not calls)
            fixture.evaluate("document.querySelector('.pc-main-page-layout').__vue__.$pinia.state.value.userStore.isLogin=true")
            receipt=tieba_fill_and_submit(fixture,{'title':'模拟新版贴吧标题','body':'模拟正文'},'123','人工智能')
            fixture.wait_for_timeout(150)
            check('new Tieba editor fills and receives ID',receipt['post_id']=='456789')
            check('site duplicate POST suppressed',len(calls)==1)
            check('editor text exact',fixture.locator('#tb-editor-title .ql-editor').inner_text()=='模拟新版贴吧标题')
            try:tieba_fill_and_submit(fixture,{'title':'another title','body':'body'},'other-user','人工智能')
            except NotSubmitted:pass
            else:raise AssertionError('identity change not rejected')
            check('Tieba wrong identity rejects before click',len(calls)==1)
            print(json.dumps({'checks':len(checks),'passed':checks,'errors':errors,'real_platform_writes':0,'output':str(output)},ensure_ascii=False))
            (output/'verification.json').write_text(json.dumps({'checks':checks,'errors':errors,'real_platform_writes':0},ensure_ascii=False,indent=2),encoding='utf-8')
        finally:
            if fixture:fixture.close()
            page.close()
            server.should_exit=True;thread.join(5)
            assert all(p in context.pages for p in original)


if __name__=='__main__':main()
