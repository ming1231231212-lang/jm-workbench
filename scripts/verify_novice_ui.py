"""Novice journey on isolated data/headless Chromium; all external traffic denied."""
import json
import socket
import threading
import time
from pathlib import Path
import uvicorn
from playwright.sync_api import sync_playwright, expect
from jm_workbench.web.app import create_app
from jm_workbench.community.models import CommunityAccount, CommunityPost, DailyPlan

ROOT=Path(__file__).resolve().parents[1]


def main():
    out=ROOT/'outputs'/('novice-qa-'+time.strftime('%Y%m%d-%H%M%S'));out.mkdir(parents=True)
    class Fake:
        checks=0
        def check(self,a,secret):self.checks+=1;return 'fixture-'+a['id']
        def publish(self,*args):raise AssertionError('no writes in this UI journey')
        def open(self,a,url):return {'message':'模拟打开原网站','url':url}
    fake=Fake();app=create_app(out/'home',worker=False,community_adapter=fake);s=app.state.community
    accounts={p:s.save_account(CommunityAccount(platform=p,name=name))['id'] for p,name in [('tieba','我的贴吧'),('juejin','我的掘金'),('weibo','我的微博')]}
    for p in ('tieba','juejin'):
        s.check_account(accounts[p]);plan=s.daily.save(DailyPlan(name='趣造AI · '+p,account_id=accounts[p],board='人工智能',rules_note='本地验收素材，仅讨论与AI工具实际使用相关的问题。'))['id'];s.daily.control(plan,'enable')
    draft=s.save(CommunityPost(request_id='novice-existing-comment',kind='reply',title='回复：AI工具收藏怎么整理',body='先按实际任务整理工具，再记录使用限制和结果，保留原始链接。',source_title='AI工具收藏很多，怎么找到真正能用的？',source_excerpt='收藏了很多AI工具，但是需要时找不到，想按任务分类。',targets=[{'account_id':accounts['tieba'],'destination':'https://tieba.baidu.com/p/12345678'}]))['id']
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(16);port=sock.getsockname()[1];base=f'http://127.0.0.1:{port}'
    server=uvicorn.Server(uvicorn.Config(app,log_level='warning'));thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    checks=[];errors=[];external=[]
    def check(name,ok=True):assert ok,name;checks.append(name)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1440,'height':1050},accept_downloads=True,reduced_motion='reduce')
        context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(base+'/') else (external.append(r.request.url),r.abort()))
        page=context.new_page();page.set_default_timeout(10000);page.on('pageerror',lambda ex:errors.append(str(ex)))
        def ready():expect(page.locator('body')).not_to_have_attribute('aria-busy','true')
        def click(action,ident=None):
            sel=f'[data-action="{action}"]'+(f'[data-id="{ident}"]' if ident is not None else '')
            page.locator(sel+':visible').first.click();ready()
        def nav(tab):page.goto(base+'/#community/'+tab);expect(page.locator('#content h1')).to_be_visible();ready()
        def close():
            if page.locator('#dialog').evaluate('e=>e.open'):click('close-dialog')
            drawer=page.locator('#community-drawer')
            if drawer.count() and drawer.evaluate('e=>e.open'):click('com-v2-close')
        def snap(name):page.screenshot(path=str(out/(name+'.png')),full_page=True)
        try:
            page.goto(base);expect(page.locator('#content h1')).to_have_text('今日工作')
            expect(page.locator('.novice-status')).to_contain_text('后台未启动');check('first visit exposes a stopped worker honestly')
            before=fake.checks;click('refresh');check('page refresh never starts browser identity checks',fake.checks==before)
            s.runtime=lambda:{'status':'ready','healthy':True,'operations':[],'message':'后台已就绪，按发布安排执行'}
            click('refresh');expect(page.locator('.novice-status')).to_contain_text('后台已就绪')
            expect(page.locator('.today-plan')).to_have_count(2);expect(page.locator('.todo-list')).to_contain_text('需要补充帖子');check('platform progress and missing materials are separate actionable items');snap('today-desktop')
            for tab,title in [('content','内容与记录'),('plans','发布安排'),('accounts','平台账号'),('overview','今日工作')]:
                page.locator(f'#nav a[href="#community/{tab}"]').click();expect(page.locator('#content h1')).to_have_text(title)
                check('primary navigation '+tab,page.locator('#nav a[aria-current="page"]').count()==1)
            page.go_back();expect(page.locator('#content h1')).to_have_text('平台账号');check('browser back returns to the actual selected view')
            click('com-add-platform','wechat_mp');expect(page.locator('[name="platform"]')).to_have_value('wechat_mp');expect(page.locator('.com-api-secret')).not_to_be_visible()
            expect(page.locator('.com-browser-help')).to_contain_text('当前不会自动提交');page.locator('[name="name"]').fill('我的公众号');page.locator('#com-account-form button.primary').click();ready();expect(page.locator('#dialog')).not_to_be_visible()
            wechat=next(a for a in s.state()['accounts'] if a['platform']=='wechat_mp');check('WeChat account is configured without asking for a password or unsupported API')
            click('com-v2-account',wechat['id']);expect(page.locator('#community-drawer')).to_contain_text('网页发布');expect(page.locator('#community-drawer [data-action="com-check"]')).to_have_count(0);close()
            nav('content');click('com-v2-compose');click('com-new');page.locator('[name="title"]').fill('一起来建设趣造AI工具网站');page.locator('[name="body"]').fill('趣造AI：https://quzaoai.com\n欢迎分享实际使用过的AI工具、反馈问题和建议，一起建设大家的网站。')
            page.locator(f'[name="account_ids"][value="{wechat["id"]}"]').check();expect(page.locator('[name="platform_tags"]')).not_to_be_visible();page.locator('#com-post-form button[value="draft"]').click();ready();expect(page.locator('#dialog')).not_to_be_visible()
            post=next(p for p in s.state()['posts'] if p['payload']['title']=='一起来建设趣造AI工具网站');check('simple composition saves an exact local draft without publication',post['state']=='draft' and not s.jobs(post['id']))
            click('com-view',post['id']);expect(page.locator('.article-preview')).to_contain_text('https://quzaoai.com');click('com-edit',post['id']);expect(page.locator('[name="body"]')).to_have_value(post['payload']['body']);click('close-dialog');check('draft editing preserves full text and website link')
            page.locator('.content-export summary').click()
            with page.expect_download() as downloaded:page.locator('.content-export a[download]').first.click()
            downloaded.value.save_as(str(out/'wechat-content.md'));check('content export download keeps the website link','quzaoai.com' in (out/'wechat-content.md').read_text(encoding='utf-8'))
            click('com-launch',post['id']);expect(page.locator('#community-drawer')).to_contain_text('待网页发布');job=s.jobs(post['id'])[0];check('prepare web publication creates a manual target, never an automatic job',job['state']=='manual')
            click('com-open-job',job['id']);click('com-record',job['id']);page.locator('[name="url"]').fill('https://mp.weixin.qq.com/s/local_fixture_article');page.locator('#com-record-form button.primary').click();ready();expect(page.locator('#dialog')).not_to_be_visible();expect(page.locator('#community-drawer')).to_contain_text('用户登记，尚未独立核验');check('registered web result is not counted as a platform success');close()
            click('com-v2-kind','reply');click('com-view',draft);expect(page.locator('.quote-preview')).to_contain_text('按任务分类');expect(page.locator('.article-preview')).to_contain_text('保留原始链接');check('comment record keeps original post context and full comment');close()
            nav('accounts');click('com-new-account');page.locator('[name="name"]').fill('误加的贴吧');page.locator('#com-account-form button.primary').click();ready();expect(page.locator('#dialog')).not_to_be_visible()
            extra=next(a for a in s.state()['accounts'] if a['name']=='误加的贴吧');click('com-v2-account',extra['id']);click('com-delete-account',extra['id']);page.locator('#com-delete-account-form button.danger').click();ready();expect(page.locator('#dialog')).not_to_be_visible();check('extra unused account can be removed',all(a['id']!=extra['id'] for a in s.state()['accounts']))
            for width in (1440,1024,390):
                page.set_viewport_size({'width':width,'height':950})
                for tab in ('overview','content','plans','accounts'):
                    nav(tab);check(f'{width}px fits '+tab,page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    if tab=='overview':snap('today-'+str(width))
            click('com-v2-menu');expect(page.locator('.sidebar')).to_be_visible();page.locator('#nav a[href="#community/content"]').click();expect(page.locator('.community-mobile-menu')).to_have_attribute('aria-expanded','false');check('mobile menu closes after choosing a view')
            page.set_viewport_size({'width':1440,'height':1050})
            s.cfg.config.save({'community_browser_execution':'web'})
            with s.store.connect(True) as db:db.execute("UPDATE community_plans SET state='paused',message='自动控制已取消'")
            before=fake.checks
            nav('overview');expect(page.locator('#community-view')).to_contain_text('每日自动发帖与评论已停用');snap('without-extension-home');check('home explains web workflow without claiming automatic sending')
            nav('accounts');click('com-v2-account',accounts['tieba']);expect(page.locator('#community-drawer [data-action="com-check"]')).to_have_count(0);expect(page.locator('#community-drawer')).to_contain_text('网页发布');close();check('old verified browser account no longer offers pairing checks')
            click('com-v2-account',accounts['tieba']);page.goto(base+'/#community/content');expect(page.locator('#community-drawer')).not_to_be_visible();page.go_back();expect(page.locator('#content h1')).to_have_text('平台账号');expect(page.locator('#community-drawer')).not_to_be_visible();check('hash navigation and browser back close stale detail drawers')
            s.launch(draft);job=s.jobs(draft)[0]
            with s.store.connect(True) as db:db.execute("UPDATE community_jobs SET state='paused' WHERE id=?",(job['id'],))
            nav('content');click('com-v2-kind','reply');click('com-view',draft);expect(page.locator('#community-drawer [data-action="com-resume"]')).to_have_count(0)
            click('com-to-web',job['id']);expect(page.locator('#community-drawer')).to_contain_text('待网页发布');check('proven unsent historical comment can explicitly switch to web with same text',s.jobs(draft)[0]['id']==job['id'])
            click('com-open-job',job['id']);click('com-record',job['id']);page.locator('[name="url"]').fill('https://tieba.baidu.com/p/12345678?pid=87654321#87654321');page.locator('#com-record-form button.primary').click();ready();expect(page.locator('#dialog')).not_to_be_visible();expect(page.locator('#community-drawer')).to_contain_text('用户登记，尚未独立核验');close();check('web comment receipt records exact destination without claiming an automatic result',fake.checks==before)
            check('no JavaScript exceptions or external requests',not errors and not external)
        except Exception:
            snap('failure');raise
        finally:
            (out/'report.json').write_text(json.dumps({'passed':len(checks),'checks':checks,'errors':errors,'external_requests':external,'real_publications':0},ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'passed':len(checks),'output':str(out),'errors':errors},ensure_ascii=False));context.close();browser.close();server.should_exit=True;thread.join(5);sock.close()


if __name__=='__main__':main()
