import json
from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from jm_workbench.web.app import create_app
from jm_workbench.core.config import Config
from jm_workbench.community.models import CommunityAccount,CommunityPost,NativeBindInput,DailyPlan
from jm_workbench.community.service import SHANGHAI


@pytest.fixture
def ranged(tmp_path):
    Config(tmp_path).save({'community_browser_execution':'native'})
    class Fake:
        def __init__(self):self.sent=[]
        def check(self,a,*_):return a['native_binding']['identity']
        def publish(self,a,secret,p,target):
            self.sent.append((a['platform'],p['body']))
            prefix={'tieba':'https://tieba.baidu.com/p/','juejin':'https://juejin.cn/post/','zhihu':'https://zhuanlan.zhihu.com/p/'}[a['platform']]
            ident=str(1234567890123456+len(self.sent))
            return {'post_id':ident,'url':prefix+ident,'visibility':'unverified'}
    f=Fake();app=create_app(tmp_path,worker=False,community_adapter=f);s=app.state.community
    now=[datetime(2026,10,15,12,tzinfo=SHANGHAI).timestamp()];s.clock=lambda:now[0]
    plans={}
    for platform,identity,profile,board in [
        ('tieba','tieba:tb.fixture','https://tieba.baidu.com/home/main?id=tb.fixture','ai工具'),
        ('juejin','1234567890123456','https://juejin.cn/user/1234567890123456','人工智能'),
        ('zhihu','zhihu:fixture','https://www.zhihu.com/people/fixture','')]:
        a=s.save_account(CommunityAccount(name='fixture '+platform,platform=platform))
        a=s.bind_native(a['id'],NativeBindInput(version=a['version'],identity=identity,name='fixture',profile_url=profile))['account']
        topics=[{'title':'隔离测试文稿编号'+str(i),'body':'仅用于模拟测试，逐项检查材料与自己的结论。'*15+'主题'+str(i)+'（AI辅助整理）','platform_tags':['人工智能']} for i in range(5)]
        p=s.daily.save(DailyPlan(name='fixture '+platform,account_id=a['id'],board=board,hour=1,replies_per_day=0,topics=topics,rules_note='仅用于隔离测试，只发帖子不评论'))['id']
        with s.store.connect(True) as db:db.execute("INSERT INTO community_plan_days VALUES(?,?,'waiting','offline',?,?)",(p,'2026-10-15',now[0],now[0]))
        plans[platform]=p
    now[0]=datetime(2026,10,18,13,tzinfo=SHANGHAI).timestamp()
    return s,f,plans,now,app


@pytest.mark.parametrize('platform',['tieba','juejin','zhihu'])
def test_only_requested_date_is_registered_idempotently_without_sending(ranged,platform):
    s,f,plans,now,_=ranged;p=plans[platform]
    rows=s.backfill.preview([p],'2026-10-17',0,from_day='2026-10-17')
    assert len(rows)==1 and rows[0]['day']=='2026-10-17' and rows[0]['kind']=='thread'
    assert s.backfill.register([p],'2026-10-17',0,from_day='2026-10-17')['created']==1
    assert s.backfill.register([p],'2026-10-17',0,from_day='2026-10-17')['created']==0
    assert len(s.state()['posts'])==1 and not f.sent and not s.store.rows('SELECT * FROM community_jobs')
    assert s.backfill.state()['items'][0]['platform']==platform


def test_queue_range_does_not_reactivate_older_history_and_keeps_daily_cap(ranged):
    s,f,plans,now,_=ranged;p=plans['zhihu']
    s.backfill.register([p],'2026-10-17',0)
    old=next(x for x in s.backfill.state()['items'] if x['day']=='2026-10-15')['post_id']
    s.daily.control(p,'enable')
    assert s.backfill.queue(p,from_day='2026-10-16',through_day='2026-10-17')['queued']==2
    assert not s.jobs(old)
    assert s.backfill.queue(p,from_day='2026-10-16',through_day='2026-10-17')['queued']==0
    s.tick();s.tick();now[0]+=1801;s.tick();assert len(f.sent)==1
    queued=s.store.rows("SELECT * FROM community_jobs WHERE state='queued'")
    assert len(queued)==1 and queued[0]['due']>=datetime(2026,10,19,tzinfo=SHANGHAI).timestamp()
    now[0]=datetime(2026,10,19,1,tzinfo=SHANGHAI).timestamp();s.tick()
    assert len(f.sent)==2 and not s.jobs(old)


def test_registration_does_not_fill_unrelated_plans_or_older_blanks(ranged):
    s,f,plans,now,_=ranged;p=plans['tieba'];other=plans['juejin']
    with s.store.connect(True) as db:
        for ident,plan,day in [('older',p,'2026-10-15'),('other',other,'2026-10-17')]:
            db.execute("INSERT INTO community_backfill VALUES(?,?,?,'thread',1,'',?,'untouched')",(ident,plan,day,now[0]))
    before=s.store.rows('SELECT * FROM community_backfill ORDER BY id')
    s.backfill.register([p],'2026-10-17',0,from_day='2026-10-17')
    assert s.store.rows("SELECT * FROM community_backfill WHERE id IN ('older','other') ORDER BY id")==before
    assert len(s.state()['posts'])==1 and not f.sent


@pytest.mark.parametrize('begin,end',[('2026-10-18','2026-10-18'),('2026-10-17','2026-10-16')])
def test_invalid_range_cannot_change_records(ranged,begin,end):
    s,f,plans,_,_=ranged;p=plans['tieba']
    with pytest.raises(ValueError):s.backfill.register([p],end,0,from_day=begin)
    with pytest.raises(ValueError):s.backfill.queue(p,from_day=begin,through_day=end)
    assert not s.store.rows('SELECT * FROM community_backfill') and not f.sent


def test_api_preserves_date_range_and_zero_comments(ranged):
    s,f,plans,_,app=ranged;p=plans['zhihu']
    with TestClient(app,base_url='http://127.0.0.1:8776') as client:
        headers={'X-JM-Token':client.get('/api/state').json()['token']}
        body={'plan_ids':[p],'from_day':'2026-10-17','through_day':'2026-10-17','replies_per_day':0}
        assert client.post('/api/community/backfill/preview',json=body,headers=headers).json()['items'][0]['day']=='2026-10-17'
        assert client.post('/api/community/backfill/register',json=body,headers=headers).json()['created']==1
        s.daily.control(p,'enable')
        r=client.post('/api/community/backfill/'+p+'/queue',json={'from_day':'2026-10-17','through_day':'2026-10-17'},headers=headers)
        assert r.status_code==200 and r.json()['queued']==1
    assert not f.sent


def test_explicit_backfill_schedule_survives_midnight_and_waits_until_one(ranged):
    s,f,plans,now,_=ranged;p=plans['zhihu']
    s.backfill.register([p],'2026-10-17',0,from_day='2026-10-17')
    item=s.backfill.state()['items'][0];post=s.state()['posts'][0]
    data=post['payload'];data['schedule_at']=datetime(2026,10,19,1,tzinfo=SHANGHAI).timestamp()
    s.save(CommunityPost(**data),post['id']);s.daily.control(p,'enable')
    assert s.backfill.queue(p,from_day='2026-10-17',through_day='2026-10-17')['queued']==1
    s.tick();assert not f.sent
    now[0]=datetime(2026,10,19,0,59,tzinfo=SHANGHAI).timestamp();s.tick();assert not f.sent
    now[0]+=60;s.tick();assert len(f.sent)==1
    assert s.jobs(item['post_id'])[-1]['state']=='submitted'
