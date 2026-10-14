"""Isolated local UI contract: fake accounts, no external requests or publications."""
import json
import socket
import threading
import time
from datetime import datetime
from pathlib import Path
import uvicorn
from playwright.sync_api import sync_playwright,expect
from jm_workbench.core.config import Config
from jm_workbench.web.app import create_app
from jm_workbench.community.models import CommunityAccount
from jm_workbench.community.service import SHANGHAI

ROOT=Path(__file__).resolve().parents[1]

def main():
    out=ROOT/'outputs'/('native-daily-ui-'+time.strftime('%Y%m%d-%H%M%S'));out.mkdir(parents=True)
    Config(out/'home').save({'community_browser_execution':'native'})
    class Fake:
        sent=[]
        def check(self,a,secret):return a['native_binding']['identity']
        def publish(self,*args):self.sent.append(args);raise AssertionError('No writes allowed')
        def open(self,*args):raise AssertionError('No external browser opening allowed')
    fake=Fake();app=create_app(out/'home',worker=False,community_adapter=fake);s=app.state.community
    s.clock=lambda:datetime(2026,10,14,13,0,tzinfo=SHANGHAI).timestamp()
    account=s.save_account(CommunityAccount(platform='zhihu',name='知乎验收账号'))
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(16);port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='warning'))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    checks=[];external=[];errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);context=browser.new_context();page=context.new_page()
        page.set_default_timeout(10000);page.on('pageerror',lambda e:errors.append(str(e)))
        def route(request):
            if request.request.url.startswith(f'http://127.0.0.1:{port}/'):request.continue_()
            else:external.append(request.request.url);request.abort()
        context.route('**/*',route)
        try:
            page.goto(f'http://127.0.0.1:{port}/#community/accounts')
            page.locator(f'[data-action="com-v2-account"][data-id="{account["id"]}"]').click()
            page.locator('[data-action="com-bind-native"]').click()
            page.locator('#com-native-form [name="profile_url"]').fill('https://www.zhihu.com/people/fixture-owner')
            page.locator('#com-native-form [name="name"]').fill('验收作者')
            assert page.locator('#com-native-form [name="identity"]').count()==0
            page.locator('#com-native-form button.primary').click()
            expect(page.locator('#dialog')).not_to_be_visible()
            assert s.account(account['id'])['identity']=='zhihu:fixture-owner'
            checks.append('simple homepage form derives identity and freezes binding')
            page.goto(f'http://127.0.0.1:{port}/#community/plans')
            page.locator('[data-action="com-plan-new"]').first.click()
            expect(page.locator('[name="wizard_platform"]')).to_have_value('zhihu')
            page.locator('#com-v2-wizard button[value="next"]').click()
            page.locator('[name="name"]').fill('知乎明日起执行')
            expect(page.locator('[name="board"]')).to_have_value('')
            assert page.locator('[name="board"]').get_attribute('readonly') is not None
            page.locator('[name="rules_note"]').fill('围绕原帖具体问题回复，帖子与评论内容不重复。')
            page.locator('#com-v2-wizard button[value="next"]').click()
            page.locator('[name="start_date"]').fill('2026-10-15')
            page.locator('[name="start_time"]').fill('10:00')
            page.locator('[name="auto_prepare"]').select_option('true')
            page.locator('[name="search_terms"]').fill('AI，工作流')
            page.locator('#com-v2-wizard button[value="save"]').click()
            expect(page.locator('#dialog')).not_to_be_visible()
            plan=s.daily.state()[0]
            assert plan['payload']['start_date']=='2026-10-15' and plan['state']=='paused'
            checks.append('Zhihu wizard preserves future date and empty board without starting')
            page.locator('[data-action="com-plan-enable"]').first.click()
            expect(page.locator('#community-drawer')).to_contain_text('已启用')
            page.locator('[data-action="com-plan-today"]').first.click()
            assert not s.state()['posts'] and not fake.sent
            expect(page.locator('#community-drawer')).to_contain_text('2026/10/15 10:00:00')
            checks.append('enable and arrange-today cannot send before start date')
            assert plan['payload']['auto_prepare'] and plan['payload']['search_terms']==['AI','工作流']
            expect(page.locator('#community-drawer')).to_contain_text('每日自动准备')
            with page.expect_response(lambda r: r.url.endswith('/prepare-materials')) as response:
                page.locator('[data-action="com-plan-prepare-materials"]').click()
            assert response.value.status==200, response.value.text()
            assert s.materials.state(plan['id'])[0]['state']=='requested'
            assert not s.state()['posts'] and not fake.sent
            checks.append('automatic supply settings persist and check button only requests preparation')
            assert not external and not errors
            checks.append('no external requests browser exceptions or publications')
            result={'passed':len(checks),'checks':checks,'external':external,'errors':errors,'fake_submissions':len(fake.sent)}
            (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'passed':len(checks),'output':str(out)},ensure_ascii=False))
        finally:
            context.close();browser.close();server.should_exit=True;thread.join(timeout=3)

if __name__=='__main__':main()
