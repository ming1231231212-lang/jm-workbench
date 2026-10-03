"""Isolated local UI and worker test; all publication uses a fake adapter."""
import json,socket,threading,time
from pathlib import Path
from datetime import datetime,timedelta,timezone
from playwright.sync_api import sync_playwright,expect
import uvicorn
from jm_workbench.web.app import create_app
from jm_workbench.adapters.chrome import endpoint
from jm_workbench.community.models import CommunityAccount,DailyPlan


def main():
    root=Path(__file__).resolve().parents[1];out=root/'outputs'/('daily-ui-'+time.strftime('%Y%m%d-%H%M%S'));out.mkdir(parents=True)
    class Fake:
        sent=[]
        def check(self,*args):return 'fixture-user'
        def publish(self,a,secret,p,t):
            self.sent.append(p)
            return {'post_id':'123456','url':'https://tieba.baidu.com/p/123456','visibility':'unverified'}
    fake=Fake();app=create_app(out/'home',worker=False,community_adapter=fake);s=app.state.community
    a=s.save_account(CommunityAccount(platform='tieba',name='每日计划验收账号'));s.check_account(a['id'])
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(16);port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='warning'));t=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);t.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    checks=[];errors=[]
    def check(name):checks.append(name)
    with sync_playwright() as pw:
        b=pw.chromium.connect_over_cdp(endpoint(Path(r'D:\Codex\个人工作台\项目\Codex-Chrome\User Data')));c=b.contexts[0];original=list(c.pages);p=c.new_page()
        p.on('pageerror',lambda ex:errors.append(str(ex)));p.set_default_timeout(10000)
        try:
            p.goto(f'http://127.0.0.1:{port}/#community')
            p.locator('[data-action="com-tab"][data-id="plans"]').click();p.locator('[data-action="com-plan-new"]').click()
            p.locator('[name="name"]').fill('AI生态每日验收')
            p.locator('[name="rules_note"]').fill('这是本机隔离验收素材，不会在真实贴吧发布任何内容')
            p.locator('#com-plan-form button.primary').click();expect(p.locator('#dialog')).not_to_be_visible()
            expect(p.locator('#content')).to_contain_text('AI生态每日验收');assert not fake.sent;check('settings save without starting')
            p.locator('[data-action="com-plan-topic"]').click();p.locator('[name="title"]').fill('按场景选择AI工具验收标题')
            p.locator('[name="body"]').fill('这是一份有足够长度的原创测试正文，专门用来核对每日计划的内容展示。')
            p.locator('#com-plan-material-form button.primary').click();expect(p.locator('#dialog')).not_to_be_visible()
            expect(p.locator('#content')).to_contain_text('未用主题素材 1 篇');check('topic material form and inventory')
            plan=s.state()['plans'][0];d=plan['payload'];d['replies']=[{'url':'https://tieba.baidu.com/p/'+str(123456+i),'title':'原帖问题'+str(i),'excerpt':'这是原帖的完整问题片段，用于验证来源记录。','body':'这是给第'+str(i)+'个不同帖子写的独立评论，包含实际建议与对应原帖上下文。'} for i in range(5)]
            s.daily.save(DailyPlan(**d),plan['id'])
            p.locator('[data-action="refresh"]').click();expect(p.locator('#content')).to_contain_text('未用评论素材 / 规则 5 条')
            p.locator('[data-action="com-plan-enable"]').click();expect(p.locator('#content')).to_contain_text('已启用')
            p.locator('[data-action="com-plan-today"]').click();expect(p.locator('#content')).to_contain_text('已安排帖子 1/1、评论 5/5')
            assert len(s.state()['posts'])==6 and not fake.sent;check('one plus five planned without a fake success label')
            p.locator('[data-action="com-plan-today"]').click();expect(p.locator('#toast')).to_contain_text('不会重复');assert len(s.state()['posts'])==6;check('repeat arrange today is idempotent')
            p.locator('[data-action="com-tab"][data-id="replies"]').first.click();expect(p.locator('.community-post')).to_have_count(5)
            expect(p.locator('#content')).to_contain_text('独立评论');check('five replies and full text visible')
            p.locator('[data-action="com-view"]').first.click();expect(p.locator('#dialog')).to_contain_text('评论内容');expect(p.locator('#dialog')).to_contain_text('目标帖子：')
            expect(p.locator('#com-copy-body')).to_contain_text('独立评论');p.locator('#dialog [data-action="close-dialog"]').click();check('reply source and submitted body remain inspectable')
            p.locator('[data-action="com-tab"][data-id="posts"]').first.click();expect(p.locator('.community-post')).to_have_count(1);expect(p.locator('#content')).to_contain_text('原创测试正文');check('thread and comment tabs are separate')
            s.tick();assert len(fake.sent)==1
            p.locator('[data-action="com-tab"][data-id="plans"]').first.click();expect(p.locator("body")).to_have_attribute("aria-busy","false");p.locator('[data-action="refresh"]').click();expect(p.locator('#content')).to_contain_text('已提交 1/1');check('result counts reflect actual fake receipt');expect(p.locator("body")).to_have_attribute("aria-busy","false")
            p.locator('[data-action="com-plan-pause"]').click();expect(p.locator('#content')).to_contain_text('已暂停');assert all(j['state']!='queued' for r in s.state()['posts'] for j in r['jobs']);check('pause stops remaining queued replies')
            assert not errors;check('no browser JavaScript errors')
        finally:p.close();server.should_exit=True;t.join(5)
        assert all(not p.is_closed() for p in original);check('original tabs preserved')
    (out/'result.json').write_text(json.dumps({'checks':checks,'real_sends':0},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':checks,'real_sends':0,'output':str(out)},ensure_ascii=False))

if __name__=='__main__':main()
