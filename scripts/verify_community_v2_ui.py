"""Approved community UI acceptance. Isolated DB, fake adapter, no production writes."""
import json
import re
import socket
import threading
import time
import traceback
from pathlib import Path
import uvicorn
from playwright.sync_api import sync_playwright, expect
from jm_workbench.web.app import create_app
from jm_workbench.adapters.chrome import endpoint
from jm_workbench.community.adapters import NotSubmitted
from jm_workbench.community.models import CommunityAccount,CommunityPost,DailyPlan

ROOT=Path(__file__).resolve().parents[1]

def main():
    output=ROOT/'outputs'/('community-v2-qa-'+time.strftime('%Y%m%d-%H%M%S'));output.mkdir(parents=True)
    class Fake:
        sent=[]
        opened=[]
        offline={'juejin'}
        def check(self,a,secret):
            if a['platform'] in self.offline:raise NotSubmitted('等待账号登录')
            return 'fixture-'+a['id']
        def publish(self,a,secret,payload,target):
            self.sent.append((a['id'],payload,target))
            return {'post_id':'1234567','url':'https://tieba.baidu.com/p/1234567','visibility':'unverified'}
        def open(self,a,url):self.opened.append((a['id'],url));return {'message':'模拟打开账号浏览器'}
        def discover(self,*args):return []
    fake=Fake();app=create_app(output/'home',worker=False,community_adapter=fake);s=app.state.community
    accounts={}
    for p,name in [('tieba','贴吧 · 测试账号'),('juejin','掘金 · 测试账号'),('csdn','CSDN · 测试账号'),('reddit','Reddit · 测试账号')]:
        accounts[p]=s.save_account(CommunityAccount(platform=p,name=name))['id']
        if p in ('tieba','csdn'):s.check_account(accounts[p])
    plans={}
    for p in ('tieba','juejin','csdn'):
        plans[p]=s.daily.save(DailyPlan(name=p+' · 日常计划',account_id=accounts[p],board='人工智能' if p!='csdn' else '博客',rules_note='本地测试：围绕真实技术问题提供经验，不重复内容。'))['id']
    with s.store.connect(True) as db:db.execute("INSERT INTO community_risk VALUES('csdn','测试平台限制，不应自动解除',?)",(s.clock(),))
    for i in range(10):
        s.save(CommunityPost(request_id='ui-fixture-'+str(i),kind='reply' if i%2 else 'thread',title='本地界面测试内容 '+str(i),body='这是本地测试正文，包含完整的内容与具体操作，不会提交到真实平台。',source_title='原帖问题 '+str(i) if i%2 else '',source_excerpt='原帖保留的完整问题描述，用于测试评论上下文与正确的目标关系。',targets=[{'account_id':accounts['tieba'],'destination':'https://tieba.baidu.com/p/'+str(1234567+i) if i%2 else '人工智能'}]))
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(16);port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='warning'));thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    checks=[];errors=[];external=[];console_errors=[]
    def check(name,ok=True):assert ok,name;checks.append(name)
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp(endpoint(Path(r'D:\Codex\个人工作台\项目\Codex-Chrome\User Data')),timeout=15000)
        context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True,reduced_motion='reduce');page=context.new_page();page.set_default_timeout(10000)
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('console',lambda msg:console_errors.append(msg.text) if msg.type=='error' else None)
        def route(r):
            if not r.request.url.startswith(f'http://127.0.0.1:{port}/'):
                external.append(r.request.url);r.abort()
            else:r.continue_()
        context.route('**/*',route)
        def click(action,id=None,scope=''):
            locator=f'{scope} [data-action="{action}"]' if scope else f'[data-action="{action}"]'
            if id is not None:locator+=f'[data-id="{id}"]'
            page.locator(locator).first.click()
            expect(page.locator('body')).to_have_attribute('aria-busy','false')
        def close():
            expect(page.locator('body')).not_to_have_attribute('aria-busy','true')
            if page.locator('#dialog').evaluate('el=>el.open'):click('close-dialog')
            if page.locator('#community-drawer').evaluate('el=>el.open'):click('com-v2-close')
            expect(page.locator('#community-drawer')).not_to_be_visible()
        def tab(name):close();click('com-tab',name)
        def snap(name):
            page.locator('#toast').evaluate('el=>el.hidden=true')
            page.screenshot(path=str(output/(name+'.png')),full_page=True)
        def wizard_next():page.locator('#com-v2-wizard button[value="next"]').click();expect(page.locator('body')).to_have_attribute('aria-busy','false')
        try:
            page.goto(f'http://127.0.0.1:{port}/#community');expect(page.locator('[data-plan-row]')).to_have_count(3)
            check('three primary community views',page.locator('.view-tabs button').count()==3)
            check('six original module routes remain',page.locator('#nav a').count()==6)
            snap('plans-desktop')
            page.locator('#community-search').fill('不存在的计划');expect(page.get_by_text('没有匹配的计划')).to_be_visible()
            check('live search retains focus',page.locator('#community-search').evaluate('el=>document.activeElement===el'))
            click('com-v2-clear');page.locator('[data-com-filter="platform"]').select_option('csdn');expect(page.locator('[data-plan-row]')).to_have_count(1)
            check('platform filter keeps exact matching plan');click('com-v2-clear')
            click('com-v2-plan',plans['csdn']);expect(page.locator('#community-drawer')).to_contain_text('测试平台限制')
            check('platform pause stays distinct from logged-in status',page.locator('#community-drawer [data-action="com-plan-enable"]').count()==0)
            page.keyboard.press('Escape');expect(page.locator('#community-drawer')).not_to_be_visible()
            click('com-plan-new');wizard_next()
            page.locator('#com-v2-wizard [name="name"]').fill('新增每日计划测试')
            page.locator('#com-v2-wizard [name="board"]').fill('人工智能')
            page.locator('#com-v2-wizard [name="source_boards"]').fill('人工智能')
            page.locator('#com-v2-wizard [name="rules_note"]').fill('本地模拟验收：只讨论符合版面要求的具体技术问题。')
            wizard_next();click('com-v2-wizard-back');expect(page.locator('[name="name"]')).to_have_value('新增每日计划测试');wizard_next()
            page.locator('[name="replies_per_day"]').select_option('0')
            snap('wizard-desktop')
            page.locator('#com-v2-wizard button[value="save"]').click();expect(page.locator('#dialog')).not_to_be_visible();expect(page.locator('#community-drawer')).to_be_visible()
            new=next(p for p in s.state()['plans'] if p['payload']['name']=='新增每日计划测试')
            check('three-step plan saves without launch and preserves inputs',new['state']=='paused' and not fake.sent)
            check('article-only setting persists through wizard',new['payload']['replies_per_day']==0)
            click('com-v2-drawer-tab','rules');click('com-plan-topic',new['id']);page.locator('[name="title"]').fill('本地验收帖子素材标题');page.locator('[name="body"]').fill('这是用于本地测试每日计划的帖子素材，不会发送到真实平台。');page.locator('#com-plan-material-form button.primary').click();expect(page.locator('#dialog')).not_to_be_visible()
            check('materials persist against the selected plan',len(s.daily.get(new['id'])['payload']['topics'])==1)
            click('com-plan-edit',new['id']);expect(page.locator('[name="account_id"]')).to_be_disabled();click('close-dialog')
            check('existing plan keeps fixed account binding')
            click('com-plan-enable',new['id']);check('enable uses existing backend action',s.daily.get(new['id'])['state']=='enabled')
            click('com-plan-today',new['id']);check('arrange today creates pending records without mock send',len(s.state()['posts'])==11 and not fake.sent)
            expect(page.locator('#community-drawer')).to_contain_text('自动评论已关闭')
            click('com-v2-drawer-tab','summary')
            expect(page.locator('#community-drawer')).to_contain_text('下次动作')
            check('plan drawer explains next action and independent article execution')
            click('com-plan-pause',new['id']);linked=next(p for p in s.state()['posts'] if p.get('plan_id')==new['id']);check('plan pause holds queued jobs',linked['jobs'][0]['state']=='paused')
            click('com-v2-drawer-tab','content');click('com-view',linked['id'],scope='#community-drawer');expect(page.locator('.article-preview')).to_contain_text('本地测试每日计划')
            check('plan to exact content preserves full original body')
            click('com-resume',linked['id']);s.tick();close();click('refresh');click('com-tab','content');click('com-view',linked['id']);expect(page.locator('#community-drawer')).to_contain_text('已提交 · 待核验')
            check('fake execution receipt is not shown as public visibility',len(fake.sent)==1 and page.locator('#community-drawer').get_by_text('公开可见性：未核验').count()==1)
            close();click('com-v2-kind','reply');expect(page.locator('[data-post-row]')).to_have_count(5)
            reply=next(p for p in s.state()['posts'] if p['payload']['kind']=='reply')
            click('com-view',reply['id']);expect(page.locator('.quote-preview')).to_contain_text('完整问题描述');check('comments show original target and source excerpt',page.locator('#community-drawer a').first.get_attribute('href')==reply['payload']['targets'][0]['destination'])
            page.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>window.__copied=text}})")
            click('com-v2-copy',reply['id']);check('copy preserves complete reply',page.evaluate('window.__copied')==reply['payload']['body']);snap('comment-drawer')
            close()
            with page.expect_download() as dl:click('com-v2-export')
            dl.value.save_as(str(output/'comments.csv'));check('CSV exports exact current filter',len((output/'comments.csv').read_text(encoding='utf-8-sig').splitlines())==6)
            click('com-v2-compose');click('com-new');page.locator('#com-post-form [name="title"]').fill('正式界面本地草稿验收');page.locator('#com-post-form [name="body"]').fill('本地新增草稿，检查保存之后是否能够正确地编辑并查看。');page.locator('[name="account_ids"]').first.check();page.locator('[name^="destination_"]').first.fill('人工智能');page.locator('#com-post-form button[value="draft"]').click();expect(page.locator('#dialog')).not_to_be_visible()
            draft=next(p for p in s.state()['posts'] if p['payload']['title']=='正式界面本地草稿验收');check('composer draft saves without publishing',draft['state']=='draft' and len(fake.sent)==1)
            click('com-v2-clear');snap('content-desktop');click('com-view',draft['id']);click('com-edit',draft['id']);expect(page.locator('[name="body"]')).to_have_value(draft['payload']['body']);click('close-dialog');check('draft edit retains body and account destinations')
            click('com-launch',draft['id']);close()
            other=next(p for p in s.state()['posts'] if p['state']=='draft' and p['payload']['kind']=='thread')
            s.launch(other['id']);click('refresh')
            page.locator(f'[data-com-select="{draft["id"]}"]').check()
            click('com-v2-bulk-pause')
            check('bulk pause targets selection and leaves other queue intact',s.jobs(draft['id'])[0]['state']=='paused' and s.jobs(other['id'])[0]['state']=='queued')
            page.locator('[data-com-select="all"]').check()
            with page.expect_download() as dl:click('com-v2-export-selected')
            dl.value.save_as(str(output/'selection.csv'));check('selected export creates local file',(output/'selection.csv').stat().st_size>100)
            click('com-v2-unselect')
            tab('accounts');click('com-new-account');page.locator('[name="name"]').fill('临时重复备注账号');page.locator('#com-account-form button.primary').click();expect(page.locator('#dialog')).not_to_be_visible();temp=next(a for a in s.state()['accounts'] if a['name']=='临时重复备注账号');click('com-v2-account',temp['id']);click('com-delete-account',temp['id']);click('close-dialog');check('cancel deletion retains record',any(a['id']==temp['id'] for a in s.state()['accounts']))
            click('com-delete-account',temp['id']);page.locator('#com-delete-account-form button.danger').click();expect(page.locator('#dialog')).not_to_be_visible();check('remove unused account leaves originals',len(s.state()['accounts'])==4)
            click('com-v2-account',accounts['tieba']);click('com-delete-account',accounts['tieba']);page.locator('#com-delete-account-form button.danger').click();expect(page.locator('#dialog .community-operation-error')).to_contain_text('引用');check('referenced accounts remain protected with inline explanation',len(s.state()['accounts'])==4);close()
            click('com-v2-account',accounts['juejin']);fake.offline.clear();click('com-check',accounts['juejin']);expect(page.locator('#community-drawer')).to_contain_text('已登录 · 已同步');check('connection recovery does not enable or send',s.daily.get(plans['juejin'])['state']=='paused' and len(fake.sent)==1);close()
            click('com-v2-account-mode','matrix');expect(page.locator('.matrix tbody tr')).to_have_count(20);check('all 20 platforms retained with real capability labels');snap('accounts-matrix')
            tab('plans');click('com-plan-new');wizard_next()
            page.locator('[name="name"]').fill('启用失败保留草稿测试');page.locator('[name="board"]').fill('人工智能');page.locator('[name="rules_note"]').fill('本地测试：保存成功后如果启用失败，必须保留同一个计划。');wizard_next()
            before=len(s.state()['plans'])
            context.route('**/api/community/plans/*/enable',lambda r:r.fulfill(status=400,content_type='application/json',body=json.dumps({'error':'模拟发布条件尚未就绪'})))
            page.locator('#com-v2-wizard button[value="enable"]').click();expect(page.locator('#com-v2-form-error')).to_contain_text('模拟发布条件尚未就绪')
            check('failed enable retains saved plan and form',len(s.state()['plans'])==before+1)
            context.unroute('**/api/community/plans/*/enable')
            page.locator('#com-v2-wizard button[value="save"]').click();expect(page.locator('#dialog')).not_to_be_visible()
            check('retry saves same plan instead of duplicating',len(s.state()['plans'])==before+1);close()
            click('com-v2-density');page.reload();expect(page.locator('body')).to_have_class(re.compile(r'community-dense'));check('density survives reload without storing business data')
            for width,height in [(1440,1000),(1024,800),(390,844)]:
                page.set_viewport_size({'width':width,'height':height})
                for name in ['plans','content','accounts']:
                    tab(name)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'{width} {name} page overflow'
                    assert page.locator('#community-view .table-wrap').evaluate_all('els=>els.every(el=>el.scrollWidth<=el.clientWidth+1)'),f'{width} {name} table overflow'
                check(f'{width}px layouts without page or table overflow')
            tab('plans');snap('plans-mobile');click('com-v2-menu');expect(page.locator('body')).to_have_class(re.compile(r'community-menu-open'));page.keyboard.press('Escape');check('mobile navigation opens and Escape closes')
            click('com-plan-new');wizard_next();snap('wizard-mobile');check('mobile wizard fits viewport',page.locator('#dialog').bounding_box()['width']<=390);click('close-dialog')
            page.set_viewport_size({'width':1440,'height':1000})
            for route_name in ['tasks','publishing','data','accounts','settings','community']:
                page.goto(f'http://127.0.0.1:{port}/#{route_name}');expect(page.locator('#content h1')).to_be_visible();expect(page.locator('body')).to_have_class(re.compile(r'jm-workspace'))
            check('other five modules remain reachable with the shared visual system')
            check('no browser exceptions',not errors);check('no external requests',not external)
        except Exception:
            errors.append(traceback.format_exc());snap('failure');raise
        finally:
            report={'passed':len(checks),'checks':checks,'errors':errors,'external_requests':external,'console_errors':console_errors,'fake_submissions':len(fake.sent),'output':str(output)}
            (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False));context.close();server.should_exit=True;thread.join(timeout=5)

if __name__=='__main__':main()
