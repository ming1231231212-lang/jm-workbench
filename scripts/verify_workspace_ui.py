"""Full workspace acceptance: isolated database and fake connections, never real writes."""
import json
import re
import socket
import sys
import threading
import time
import traceback
from pathlib import Path
from unittest.mock import patch
import uvicorn
from playwright.sync_api import sync_playwright, expect
from jm_workbench.web.app import create_app
from jm_workbench.adapters.chrome import endpoint
from jm_workbench.policies.comments import ADULT_CORE
from jm_workbench.policies.rules import DEFAULTS

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ['tasks','publishing','community','data','accounts','settings','overview','matrix','platforms','runs']


def main():
    out = ROOT/'outputs'/('workspace-qa-'+time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    class FakeBridge:
        def catalog(self): return {'accounts': [], 'materials': []}
    class FakeBrowser:
        def __init__(self, account): self.ident=account['id']
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def account(self): return {'account_id':'fixture-'+self.ident}
    app=create_app(out/'home',worker=False,publishing_bridge=FakeBridge())
    cfg=app.state.cfg;store=cfg.store
    cfg.browser_factory=FakeBrowser
    cfg.config.crawler_ready=lambda:True
    opened=[]
    cfg.open_account=lambda ident: opened.append(ident) or {'message':'模拟打开已配置账号'}
    account=cfg.account({'name':'快手模拟账号','platform':'ks'})
    adult=cfg.task({'name':'成人尾货模拟','platform':'ks','kind':'adult_comments','keywords':['成人用品'], 'adult_target':'keyword','comment_mode':'core_variants','comment_core':ADULT_CORE})
    cfg.task({'name':'陪玩模拟','platform':'ks','kind':'peiwang_comments','keywords':['陪玩找工作'],'templates':DEFAULTS['peiwang_comments']['templates']})
    store.add_evidence('old','ks',{'video_id':'old123456','caption':'旧批次记录'},'collected','旧批次')
    for i in range(35):
        store.add_evidence('latest','ks',{'video_id':f'video{i:06}','nickname':'测试店铺','caption':'本店成人用品库存清仓 '+str(i),'source':{'query':'成人用品'}},'skipped','本地历史判断')
    store.add_evidence('latest','ks',{'video_id':'video000000','nickname':'测试店铺','caption':'本店成人用品库存清仓 0','source':{'query':'成人用品尾货'}},'skipped','重复来源')
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(16);port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    server=uvicorn.Server(uvicorn.Config(app,log_level='warning'))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    checks=[];errors=[];external=[];screens=[]
    def check(name,ok=True): assert ok,name;checks.append(name)
    with patch('jm_workbench.services.configuration.endpoint',lambda _: 'ws://127.0.0.1:1234/fake'), sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp(endpoint(Path(r'D:\Codex\个人工作台\项目\Codex-Chrome\User Data')))
        context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True,reduced_motion='reduce')
        context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(base+'/') else (external.append(r.request.url),r.abort()))
        page=context.new_page();page.set_default_timeout(10000);expect.set_options(timeout=10000)
        page.on('pageerror',lambda ex:errors.append(str(ex)))
        def ready(): expect(page.locator('body')).not_to_have_attribute('aria-busy','true')
        def nav(route):
            page.goto(base+'/#'+route)
            expect(page.locator('#content h1')).to_be_visible()
            ready()
        def click(action,ident=None):
            selector=f'[data-action="{action}"]'+(f'[data-id="{ident}"]' if ident else '')
            page.locator(selector+':visible').first.click();ready()
        def save(form): page.locator(form+' button.primary').last.click();ready()
        def close(): click('close-dialog');expect(page.locator('#dialog')).not_to_be_visible()
        def snap(name):
            page.locator('#toast').evaluate('el=>el.hidden=true')
            page.screenshot(path=str(out/(name+'.png')),full_page=True);screens.append(name+'.png')
        try:
            for route in ROUTES:
                nav(route)
                check('shared navigation and fonts '+route,page.locator('#nav a svg').count()==6 and page.locator('.sidebar').evaluate('el=>getComputedStyle(el).backgroundColor')=='rgb(25, 37, 44)' and page.locator('body').evaluate('el=>getComputedStyle(el).fontFamily').startswith('"Microsoft YaHei"'))
                check('desktop viewport '+route,page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                if route in ['tasks','publishing','data','accounts','settings','matrix']:snap('desktop-'+route)
            nav('tasks');click('new-task')
            page.locator('#task-form [name="name"]').fill('界面采集测试')
            page.locator('#task-form [name="platform"]').select_option('dy')
            save('#task-form')
            expect(page.locator('#dialog .community-operation-error')).to_contain_text('仅支持爬虫')
            expect(page.locator('#task-form [name="name"]')).to_have_value('界面采集测试')
            check('invalid task error visible inside dialog and edits retained')
            page.locator('#task-form [name="kind"]').select_option('crawler')
            page.locator('#task-form [name="name"]').fill('界面采集测试')
            page.locator('#task-form [name="keywords"]').fill('AI工具')
            save('#task-form');expect(page.locator('#dialog')).not_to_be_visible()
            crawler=next(t for t in store.objects('task') if t['name']=='界面采集测试')
            check('crawler creation persisted with no send',crawler['kind']=='crawler' and not store.rows('SELECT * FROM attempts'))
            click('edit-task',crawler['id']);page.locator('#task-form [name="keywords"]').fill('AI互联网工具');save('#task-form')
            check('task edit roundtrip',store.get('task',crawler['id'])['keywords']==['AI互联网工具'])
            click('edit-task',adult['id']);click('preview-comment')
            expect(page.locator('#comment-preview-result')).to_contain_text('不加入发送队列');close();check('configured comment preview without queue')
            nav('accounts');click('new-account')
            page.locator('#account-form [name="name"]').fill('采集测试账号');page.locator('#account-form [name="platform"]').select_option('dy');save('#account-form')
            other=next(a for a in store.objects('account') if a['name']=='采集测试账号')
            check('account creation uses separate profile',other['profile_dir']!=account['profile_dir'])
            click('edit-account',other['id']);page.locator('#account-form [name="name"]').fill('采集账号改名');save('#account-form')
            check('account edit persisted',store.get('account',other['id'])['name']=='采集账号改名')
            click('new-account');page.locator('#account-form [name="name"]').fill('重复目录测试');page.locator('#account-form [name="profile_dir"]').fill(other['profile_dir']);save('#account-form')
            expect(page.locator('#dialog .community-operation-error')).to_contain_text('另一账号');close();check('duplicate browser directory refused visibly')
            click('open-account',other['id']);check('browser open uses selected account',opened==[other['id']])
            nav('matrix');cell=page.locator(f'[data-task="{crawler["id"]}"][data-account="{other["id"]}"]');cell.check();ready();expect(cell).to_be_checked()
            check('matrix binding saved and cross-platform disabled',len(store.objects('binding'))==1 and page.locator(f'[data-task="{crawler["id"]}"][data-account="{account["id"]}"]').count()==0)
            click('launch');expect(page.locator('#toast')).to_contain_text('先检查账号连接');check('unverified account cannot launch',not store.rows('SELECT * FROM runs'))
            nav('accounts');click('check-account',other['id']);check('connection result saved',store.get('account',other['id'])['connection']=='connected')
            click('check-account',account['id']);check('comment account identity verified',store.get('account',account['id'])['identity']=='fixture-'+account['id'])
            nav('tasks');click('launch',crawler['id']);check('launch queues isolated task',len(store.rows('SELECT * FROM runs'))==1)
            click('launch');check('repeated launch does not duplicate work',len(store.rows('SELECT * FROM runs'))==1)
            nav('runs');expect(page.locator('#content')).to_contain_text('排队中');check('run progress available')
            run=store.rows('SELECT * FROM runs')[0];click('stop-run',run['id']);check('individual stop persisted',store.rows('SELECT state FROM runs')[0]['state']=='paused')
            nav('tasks');click('launch',crawler['id']);click('stop');check('stop all leaves no active work',not store.rows("SELECT * FROM runs WHERE state IN ('queued','running','waiting')"))
            nav('matrix');cell=page.locator(f'[data-task="{crawler["id"]}"][data-account="{other["id"]}"]');cell.uncheck();ready();expect(cell).not_to_be_checked();check('matrix unbind roundtrip')
            nav('data');expect(page.locator('.data-list article')).to_have_count(30);check('latest batch merges duplicates',page.locator('.data-summary').inner_text().find('36')>=0)
            click('data-next');expect(page.locator('.data-list article')).to_have_count(5);click('data-prev');check('data pagination roundtrip')
            page.locator('.comment-templates > summary').click();expect(page.locator('.template-grid')).not_to_be_visible();page.locator('.comment-templates > summary').click();check('configured comment templates expand and collapse')
            click('filter-category','inventory');expect(page.locator('.category-filter.selected')).to_have_attribute('data-id','inventory');check('category filter keeps matching data')
            page.locator('#data-filter [name="q"]').fill('不存在的数据');save('#data-filter');expect(page.get_by_text('没有符合条件的数据')).to_be_visible();check('search empty state')
            page.locator('#data-filter [name="q"]').fill('');page.locator('#data-filter [name="batch"]').select_option('all');save('#data-filter');click('filter-category','')
            page.locator('#data-filter [name="decision"]').select_option('collected');save('#data-filter');expect(page.locator('.data-list article')).to_have_count(1);check('historical batch and decision filters')
            page.locator('.data-list summary').first.click();expect(page.locator('.data-list pre')).to_be_visible();check('full evidence fields accessible')
            with page.expect_download() as download:page.locator('a[href="/api/export"]').click()
            download.value.save_as(str(out/'data.csv'));check('data export contains original evidence','旧批次记录' in (out/'data.csv').read_text(encoding='utf-8-sig'))
            nav('settings');page.locator('#settings-form [name="crawler_root"]').fill(str(out/'test-crawler'));page.locator('#settings-form [name="crawler_python"]').fill(sys.executable);save('#settings-form');expect(page.locator('#toast')).to_contain_text('配置已保存')
            page.reload();expect(page.locator('#settings-form [name="crawler_root"]')).to_have_value(str(out/'test-crawler'));check('global settings persist through reload')
            page.locator('#pub-settings-form [name="publish_gap_minutes"]').fill('45');save('#pub-settings-form');expect(page.locator('#toast')).to_contain_text('保存');page.reload();expect(page.locator('#pub-settings-form [name="publish_gap_minutes"]')).to_have_value('45');check('publishing limits saved independently')
            nav('tasks');click('com-v2-density');nav('data');expect(page.locator('body')).to_have_class(re.compile('community-dense'));nav('community');expect(page.locator('body')).to_have_class(re.compile('community-dense'));check('density remains consistent across modules and reloads')
            nav('tasks');held=[]
            page.route('**/api/publishing/state',lambda route:held.append(route))
            page.locator('#nav a[href="#publishing"]').click()
            for _ in range(30):
                if held:break
                page.wait_for_timeout(50)
            assert held
            page.locator('#nav a[href="#tasks"]').click();expect(page.locator('#content h1')).to_have_text('任务')
            result=context.request.get(base+'/api/publishing/state').text()
            for route in held:route.fulfill(status=200,content_type='application/json',body=result)
            page.wait_for_timeout(150);expect(page.locator('#content h1')).to_have_text('任务');page.unroute('**/api/publishing/state');check('slow previous route cannot replace current page')
            page.route('**/api/data?*',lambda route:route.fulfill(status=500,content_type='application/json',body=json.dumps({'error':'测试读取失败'})))
            page.locator('#nav a[href="#data"]').click();expect(page.get_by_role('heading',name='暂时无法读取数据')).to_be_visible()
            page.unroute('**/api/data?*');click('refresh');expect(page.locator('#content h1')).to_have_text('数据中心');check('failed data read has visible retry and recovers')
            for width in (1024,390):
                page.set_viewport_size({'width':width,'height':900 if width==1024 else 844})
                for route in ROUTES:
                    nav(route);check(f'{width}px no page overflow '+route,page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    if width==390 and route in ['tasks','accounts','settings','data']:snap('mobile-'+route)
            nav('tasks');check('closed mobile navigation not keyboard reachable',page.locator('.sidebar').evaluate('el=>el.inert'))
            check('mobile task actions and statuses stay within the card',page.locator('.task-list td').evaluate_all('els=>els.every(el=>el.getBoundingClientRect().right<=innerWidth && el.getBoundingClientRect().left>=0)'))
            expect(page.locator('.top-actions [data-action="launch"]')).to_be_visible();check('mobile one-click action remains available')
            click('com-v2-menu');expect(page.locator('.community-mobile-menu')).to_have_attribute('aria-expanded','true');page.locator('#nav a[href="#accounts"]').click();expect(page.locator('#content h1')).to_have_text('账号');expect(page.locator('.community-mobile-menu')).to_have_attribute('aria-expanded','false');check('mobile navigation closes after choosing destination')
            click('com-v2-menu');page.keyboard.press('Escape');expect(page.locator('.community-mobile-menu')).to_have_attribute('aria-expanded','false');check('mobile Escape returns to page')
            click('new-account');check('mobile form inside viewport',page.locator('#dialog').evaluate('el=>el.getBoundingClientRect().right<=innerWidth&&el.getBoundingClientRect().left>=0'));snap('mobile-account-form');close()
            check('no JavaScript exceptions',not errors);check('no external requests',not external)
            check('no production or simulated send triggered',not store.rows('SELECT * FROM attempts'))
        except Exception:
            errors.append(traceback.format_exc());snap('failure');raise
        finally:
            (out/'report.json').write_text(json.dumps({'passed':len(checks),'checks':checks,'errors':errors,'external_requests':external,'screenshots':screens,'output':str(out)},ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'passed':len(checks),'errors':errors,'output':str(out)},ensure_ascii=False))
            context.close();server.should_exit=True;thread.join(5);sock.close()

if __name__=='__main__': main()
