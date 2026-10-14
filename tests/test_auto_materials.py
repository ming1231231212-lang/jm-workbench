import json
from datetime import datetime
import pytest
from jm_workbench.core.config import Config
from jm_workbench.web.app import create_app
from jm_workbench.community.models import CommunityAccount,DailyPlan,NativeBindInput
from jm_workbench.community.service import SHANGHAI

@pytest.fixture
def supply(tmp_path,monkeypatch):
    Config(tmp_path).save({'community_browser_execution':'native'})
    class Fake:
        sent=[];round=0
        def check(self,a,*_):return a['native_binding']['identity']
        def publish(self,a,secret,p,target):
            self.sent.append((a['platform'],p['kind'],p['body'],target))
            return {'post_id':'fixture','url':target if p['kind']=='reply' else 'https://tieba.baidu.com/p/7890123','visibility':'account_visible'}
        def discover(self,a,terms):
            self.round+=1
            return [{'url':'https://tieba.baidu.com/p/'+str(800000+self.round*10+i),'title':'AI工作流可靠性检验'+str(i),
                     'excerpt':'AI工作流需要保存原始输入、期望输出与实际结果，再逐条检查错误来源。尤其要区分事实依据和模型推测，避免把未知信息当成已验证。',
                     'activity_at':now[0]-3600,'activity_evidence':'1小时前','heat':3,'heat_evidence':'3回复'} for i in range(5)]
    f=Fake();s=create_app(tmp_path,worker=False,community_adapter=f).state.community
    now=[datetime(2026,10,15,9,0,tzinfo=SHANGHAI).timestamp()];s.clock=lambda:now[0]
    a=s.save_account(CommunityAccount(name='fixture',platform='tieba'))
    a=s.bind_native(a['id'],NativeBindInput(version=a['version'],identity='tieba:tb.fixture',name='fixture',profile_url='https://tieba.baidu.com/home/main?id=tb.fixture'))['account']
    p=s.daily.save(DailyPlan(name='自动补充测试',account_id=a['id'],board='ai工具',rules_note='围绕原帖内容做有帮助的回复，保存来源，不发无关广告。',auto_prepare=True,start_date='2026-10-15'))['id'];s.daily.control(p,'enable')
    class Model:
        calls=0;hook=None
        def generate(self,platform,day,candidates,history,need_article,reply_count,brief):
            self.calls+=1
            if self.hook:self.hook()
            return {'article':{'title':'隔离模拟测试原创主题'+str(self.calls),'body':day+'模拟文章，核对原文依据并保留未知项。' * 20,'platform_tags':[]} if need_article else None,
              'replies':[{'url':c['url'],'title':c['title'],'excerpt':c['excerpt'],'body':day+c['url']+'针对原文保存输入与期望结果的具体建议。'} for c in candidates[:reply_count]]}
        def review(self,*_):return '隔离模拟质检通过'
    model=Model();s.materials.model=model
    # Quality rules have independent real-input tests; isolate scheduler state here.
    monkeypatch.setattr('jm_workbench.community.materials.validate_generated',lambda raw,*args:raw)
    return s,f,a,p,now,model

def test_three_days_replenish_after_empty_inventory_and_never_publish_early(supply):
    s,f,a,p,now,m=supply
    targets=set()
    for day in range(3):
        now[0]=datetime(2026,10,15+day,9,0,tzinfo=SHANGHAI).timestamp()
        s.materials.tick();assert m.calls==day+1
        assert s.materials.state(p)[0]['state']=='ready'
        s.daily.tick();assert len(s.state()['posts'])==day*6
        now[0]+=3600;s.daily.prepare(p)
        jobs=[x for x in s.state()['posts'] if x['plan_day']==f'2026-10-{15+day}']
        assert len(jobs)==6
        assert sum(x['payload']['kind']=='thread' for x in jobs)==1
        current={x['payload']['targets'][0]['destination'] for x in jobs if x['payload']['kind']=='reply'}
        assert len(current)==5 and not targets&current;targets|=current
        s.materials.prepare(p,f'2026-10-{15+day}',force=True)
        assert m.calls==day+1
    assert not f.sent # Material replenishment itself cannot submit anything.

def test_pause_during_generation_does_not_store_or_queue(supply):
    s,f,a,p,now,m=supply;m.hook=lambda:s.daily.control(p,'pause')
    s.materials.tick()
    assert s.daily.get(p)['state']=='paused' and not s.state()['posts']
    assert not s.store.rows('SELECT * FROM community_materials')

def test_failure_backoff_and_restart_preserve_materials(supply):
    s,f,a,p,now,m=supply
    m.generate=lambda *args:(_ for _ in ()).throw(ValueError('模型未完成'))
    s.materials.tick();r=s.materials.state(p)[0]
    assert r['state']=='waiting' and r['next_check']>now[0]
    s.materials.tick();assert s.materials.state(p)[0]['attempts']==1
    with s.store.connect(True) as db:db.execute("UPDATE community_preparations SET state='preparing'")
    s.materials.recover();assert s.materials.state(p)[0]['state']=='waiting'
    assert not f.sent and not s.state()['posts']

def test_manual_ready_inventory_has_priority_and_no_model_call(supply):
    s,f,a,p,now,m=supply
    from test_community_daily import config
    d=config(a['id'],topics=1,replies=5).model_dump();d['auto_prepare']=True
    s.daily.control(p,'pause');s.daily.save(DailyPlan(**d),p);s.daily.control(p,'enable')
    s.materials.tick();assert m.calls==0 and s.materials.state(p)[0]['state']=='ready'
    now[0]+=3600;s.daily.prepare(p)
    assert {x['payload']['body'] for x in s.state()['posts']}=={r['body'] for r in d['topics']+d['replies']}

@pytest.mark.parametrize('reason',['risk','version','paused'])
def test_gates_block_generation_and_keep_old_results(supply,reason):
    s,f,a,p,now,m=supply
    with s.store.connect(True) as db:
        if reason=='risk':db.execute('INSERT INTO community_risk VALUES(?,?,?)',('tieba','真实限制',now[0]))
        elif reason=='version':db.execute('UPDATE community_accounts SET version=version+1 WHERE id=?',(a['id'],))
        else:db.execute("UPDATE community_plans SET state='paused' WHERE id=?",(p,))
    s.materials.tick();assert m.calls==0 and not s.state()['posts']

def test_begin_date_hard_limit_and_six_read_rounds(supply):
    s,f,a,p,now,m=supply;now[0]-=86400
    s.materials.tick();assert m.calls==0
    now[0]+=86400
    m.generate=lambda *args:(_ for _ in ()).throw(ValueError('模型未完成'))
    for i in range(6):s.materials.prepare(p,'2026-10-15',force=True)
    s.materials.tick();assert s.materials.state(p)[0]['attempts']==6
    assert not f.sent

def test_changed_payload_invalidates_pool(supply):
    s,f,a,p,now,m=supply;s.materials.tick()
    assert s.materials.pool(s.daily.get(p),'2026-10-15')['reply']
    s.daily.control(p,'pause');d=s.daily.get(p)['payload'];d['search_terms']=['AI会议']
    s.daily.save(DailyPlan(**d),p);s.daily.control(p,'enable')
    assert not s.materials.pool(s.daily.get(p),'2026-10-15')['reply']

def test_prepare_button_is_nonblocking_and_tomorrow_is_not_published(supply):
    s,f,a,p,now,m=supply;now[0]-=86400
    r=s.daily.control(p,'prepare-materials')
    assert '后台' in r['message'] and m.calls==0
    s.materials.tick()
    assert m.calls==1 and s.materials.state(p)[0]['day']=='2026-10-15'
    s.daily.tick();assert not s.state()['posts'] and not f.sent

def test_discovery_outage_does_not_block_original_article(supply):
    s,f,a,p,now,m=supply
    f.discover=lambda *args:(_ for _ in ()).throw(TimeoutError())
    s.materials.tick();pool=s.materials.pool(s.daily.get(p),'2026-10-15')
    assert len(pool['thread'])==1 and not pool['reply']
    assert s.materials.state(p)[0]['state']=='waiting'
