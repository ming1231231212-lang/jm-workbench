"""Daily orchestration through the real tab transition and article receipt checks."""
import json
from datetime import datetime
import pytest
from jm_workbench.web.app import create_app
from jm_workbench.core.config import Config
from jm_workbench.community.models import CommunityAccount,NativeBindInput,DailyPlan
from jm_workbench.community.service import SHANGHAI
from jm_workbench.community.native import NativePublisher
from jm_workbench.community.native_articles import verify_article
from test_native_channel import Channel
from test_native_articles import result_snapshot
from test_native_cross_day import ReadOnlyResult
from test_community_replies import ctx
from test_community_daily import config


def test_three_days_three_platforms_restart_canonical_url_split_body_and_no_comments(tmp_path):
    Config(tmp_path).save({'community_browser_execution':'native'})
    now=[datetime(2026,10,15,0,59,tzinfo=SHANGHAI).timestamp()]
    class Platform:
        def __init__(self):self.sent=[];self.live={}
        def check(self,a,secret):return a['native_binding']['identity']
        def publish(self,a,secret,p,target):
            assert p['kind']=='thread'
            platform=a['platform'];ident=str(1234567890123456+len(self.sent))
            if platform=='juejin':
                path=tmp_path/'persistent-tab.json'
                tab=Channel(path,self.live.get(platform,'https://juejin.cn/editor/drafts/new?v=2'))
                if not path.exists():tab.state={'key':'owned','url':tab.live};tab.save()
                tab.call('open',url='https://juejin.cn/editor/drafts/new?v=2')
                assert tab.live.endswith('/new?v=2')
                tab.state['url']='https://juejin.cn/spost/'+ident;tab.save()
                self.live[platform]='https://juejin.cn/post/'+ident
            url={'tieba':'https://tieba.baidu.com/p/','juejin':'https://juejin.cn/post/','zhihu':'https://zhuanlan.zhihu.com/p/'}[platform]+ident
            snapshot=result_snapshot(a['native_binding']['profile_url'],p['title'],p['body'])
            snapshot['url']=url
            if platform=='juejin':
                snapshot['nodes'][0]['name']=p['title']+'正文摘要 - 掘金'
                snapshot['nodes'][2]['name']=''
                snapshot['nodes'].insert(3,dict(key='headline',parent='article',type='Text',name=p['title']+' 审核中',visible=True))
            if platform=='zhihu':
                # The platform inserts entity links inside otherwise exact text.
                for n in list(snapshot['nodes']):
                    if n['type']=='Text' and 'AI表格' in n.get('name',''):
                        before,after=n['name'].split('AI表格',1);index=snapshot['nodes'].index(n)
                        snapshot['nodes'][index:index+1]=[{**n,'name':before},
                            {**n,'key':n['key']+'link','type':'Hyperlink','name':'AI表格','value':'https://zhida.zhihu.com/search?q=AI表格'},
                            {**n,'key':n['key']+'end','name':after}]
            receipt=verify_article(NativePublisher(ReadOnlyResult(snapshot),sleep=lambda _:None,poll_attempts=1),a,a['native_binding'],p)
            self.sent.append((platform,datetime.fromtimestamp(now[0],SHANGHAI).date().isoformat(),p['kind'],receipt))
            return receipt
    f=Platform()
    def restart():
        service=create_app(tmp_path,worker=False,community_adapter=f).state.community
        service.clock=lambda:now[0];return service
    s=restart();plans=[]
    for platform,identity,profile,board in [
        ('tieba','tieba:tb.fixture','https://tieba.baidu.com/home/main?id=tb.fixture','ai工具'),
        ('juejin','1234567890123456','https://juejin.cn/user/1234567890123456','人工智能'),
        ('zhihu','zhihu:fixture','https://www.zhihu.com/people/fixture','')]:
        a=s.save_account(CommunityAccount(name='fixture '+platform,platform=platform))
        a=s.bind_native(a['id'],NativeBindInput(version=a['version'],identity=identity,name='fixture',profile_url=profile))['account']
        topics=[{'title':'来源检查实践第'+str(i)+'篇','body':'这是隔离测试：使用AI表格时，保留原始材料与来源，逐项核对缺失内容。具体测试批次'+str(i)+'。'+'核验要保留输入、输出和原文依据，并明确未验证的范围。'*8+'\n（AI辅助整理）','platform_tags':['人工智能']} for i in range(4)]
        p=s.daily.save(DailyPlan(name='fixture '+platform,account_id=a['id'],board=board,hour=1,minute=0,replies_per_day=0,rules_note='模拟测试，仅发原创帖子，不评论',topics=topics))['id']
        s.daily.control(p,'enable');plans.append(p)
    for day in range(3):
        now[0]=datetime(2026,10,15+day,0,59,tzinfo=SHANGHAI).timestamp();s=restart();s.tick()
        assert len(f.sent)==day*3
        now[0]+=60
        for _ in range(8):s.tick()
        assert len(f.sent)==(day+1)*3
        s=restart();s.tick()
        assert len(f.sent)==(day+1)*3
        for plan in s.daily.state():
            d=next(d for d in plan['days'] if d['day']==f'2026-10-{15+day}')
            assert d['counts']['thread']['submitted']==1 and d['reply_goal']==0
    assert len({(p,d) for p,d,_,_ in f.sent})==9
    assert all(j['state']=='submitted' and j['receipt']['visibility']=='account_visible' for p in s.state()['posts'] for j in p['jobs'])
    for p in plans:s.daily.control(p,'pause')
    now[0]=datetime(2026,10,18,1,0,tzinfo=SHANGHAI).timestamp();s=restart();s.tick()
    assert len(f.sent)==9 and all(p['state']=='paused' for p in s.daily.state())


def test_resolved_success_retains_reservation_and_never_resubmits(ctx):
    s,f,a,n=ctx;d=config(a);d.hour=1;d.replies_per_day=0
    p=s.daily.save(d)['id'];s.daily.control(p,'enable');s.daily.prepare(p,force=True)
    s.daily.control(p,'pause');j=s.store.rows('SELECT * FROM community_jobs')[0]
    reservation={'phase':'native_submit_reserved','submitted':None,'reserved_at':n[0]}
    with s.store.connect(True) as db:
        db.execute("UPDATE community_jobs SET state='unknown',started=?,receipt=? WHERE id=?",(n[0],json.dumps(reservation),j['id']))
    s.resolve(j['id'],'submitted','已核对原账号、标题和完整正文，与原任务一致','https://tieba.baidu.com/p/123456789')
    current=s.job(j['id']);receipt=json.loads(current['receipt'])
    assert current['started']==n[0] and current['state']=='recorded'
    assert current['snapshot']==json.loads(j['snapshot']) and current['identity']==j['identity']
    assert receipt['previous_receipt']==reservation and receipt['previous_started']==n[0]
    with pytest.raises(ValueError,match='仅结果不明'):s.resolve(j['id'],'submitted','重复登记必须被拒绝，不得创建重复回执','https://tieba.baidu.com/p/123456789')
    s.daily.control(p,'enable');assert s.daily.control(p,'continue-today')['queued']==0
    s.tick();s.daily.sync_receipts(p);s.tick()
    assert not f.sent and len(s.state()['posts'])==1
    assert s.daily.state()[0]['days'][0]['counts']['thread']['recorded']==1
