import json
import pytest
from test_community_replies import ctx,reply
from jm_workbench.community.native_runtime import reserve_submit
from jm_workbench.community.adapters import PreflightStopped,RetryablePreflight,IdentityChanged
from jm_workbench.community.native import NativeUnknown
from jm_workbench.core.db import dumps


def running(ctx):
    s,_,a,n=ctx;p=reply(s,a);s.launch(p);j=s.jobs(p)[0]
    with s.store.connect(True) as db:db.execute("UPDATE community_jobs SET state='running',started=? WHERE id=?",(n[0],j['id']))
    snap=json.loads(s.store.rows('SELECT snapshot FROM community_jobs WHERE id=?',(j['id'],))[0]['snapshot'])
    return s,{**s.account(a,True),'_native_job_id':j['id']},snap,n


def test_reservation_is_durable_and_cannot_be_repeated(ctx):
    s,a,snap,n=running(ctx)
    reserve_submit(s.cfg.config,a,snap['payload'],snap['destination'],lambda:n[0])
    row=s.store.rows('SELECT receipt FROM community_jobs WHERE id=?',(a['_native_job_id'],))[0]
    assert json.loads(row['receipt'])['phase']=='native_submit_reserved'
    with pytest.raises(NativeUnknown,match='提交占位'):reserve_submit(s.cfg.config,a,snap['payload'],snap['destination'],lambda:n[0])


@pytest.mark.parametrize('change',['stop','risk','version','body','target'])
def test_last_moment_changes_prevent_native_submit(ctx,change):
    s,a,snap,n=running(ctx);payload=snap['payload'];target=snap['destination']
    with s.store.connect(True) as db:
        if change=='stop':db.execute("UPDATE community_jobs SET message='stop_requested'")
        if change=='risk':db.execute("INSERT INTO community_risk VALUES('tieba','real restriction',?)",(n[0],))
        if change=='version':db.execute('UPDATE community_accounts SET version=version+1')
    if change=='body':payload={**payload,'body':'other content'}
    if change=='target':target='https://tieba.baidu.com/p/999999'
    with pytest.raises(PreflightStopped):reserve_submit(s.cfg.config,a,payload,target,lambda:n[0])
    assert json.loads(s.store.rows('SELECT receipt FROM community_jobs')[0]['receipt'])=={}


def test_existing_registered_write_reserves_shared_interval(ctx):
    s,a,snap,n=running(ctx)
    with s.store.connect(True) as db:
        row=dict(db.execute('SELECT * FROM community_jobs').fetchone());row.update(id='another',post_id='another',identity='other',digest='other',state='recorded',started=0,updated=n[0]-60)
        db.execute('INSERT INTO community_jobs VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
    with pytest.raises(RetryablePreflight,match='间隔'):reserve_submit(s.cfg.config,a,snap['payload'],snap['destination'],lambda:n[0])


def test_native_mode_does_not_replace_an_existing_api_adapter(ctx):
    from jm_workbench.community.adapters import CommunityAdapter
    s,_,_,_=ctx;s.cfg.config.values['community_browser_execution']='native'
    api=CommunityAdapter(s.cfg.config,transport=lambda *args,**kw:{'id':'fixture-api'})
    assert api.check({'platform':'dev'},'fixture-key')=='fixture-api'


def test_native_binding_preserves_history_and_risk_and_requires_original_identity(ctx):
    from jm_workbench.community.models import NativeBindInput
    s,_,a,_=ctx;s.cfg.config.values['community_browser_execution']='native'
    before=s.account(a);p=reply(s,a);s.launch(p)
    with s.store.connect(True) as db:db.execute("INSERT INTO community_risk VALUES('csdn','keep actual restriction',0)")
    value=NativeBindInput(version=before['version'],identity=before['identity'],profile_url='https://tieba.baidu.com/home/main?id=tb.fixture',name='fixture')
    result=s.bind_native(a,value)
    assert result['account']['version']==before['version']+1
    assert s.jobs(p)[0]['state']=='paused'
    assert s.state()['risk'][0]['reason']=='keep actual restriction'
    with pytest.raises(ValueError,match='不能替换'):s.bind_native(a,value.model_copy(update={'version':result['account']['version'],'identity':'other'}))


def test_unbound_native_zhihu_cannot_enable_a_daily_plan(ctx):
    from jm_workbench.community.models import CommunityAccount,DailyPlan
    s,_,_,_=ctx;s.cfg.config.values['community_browser_execution']='native'
    a=s.save_account(CommunityAccount(name='fixture',platform='zhihu'))
    assert a['automatic_execution'] is False
    with pytest.raises(ValueError,match='核验'):s.daily.save(DailyPlan(name='fixture plan',account_id=a['id'],rules_note='only fixture materials and authorized sample posts',start_date='2026-10-15'))


def test_only_pre_submit_overlay_can_retry_after_wait(ctx,monkeypatch):
    from contextlib import nullcontext
    from jm_workbench.community.native_runtime import NativeRuntime
    from jm_workbench.community.native import NativeStopped
    s,_,a,_=ctx;runtime=NativeRuntime(s.cfg.config)
    monkeypatch.setattr('jm_workbench.community.native_runtime.desktop_lock',lambda _:nullcontext())
    class Publisher:
        error=NativeStopped('其他窗口遮挡目标控件，未点击')
        def publish(self,*_):raise self.error
    publisher=Publisher();monkeypatch.setattr(runtime,'publisher',lambda *_:publisher)
    account={**s.account(a),'native_binding':{}}
    with pytest.raises(RetryablePreflight):runtime.publish(account,{},'')
    publisher.error=NativeUnknown('文章已进入单次提交边界，结果不明')
    with pytest.raises(NativeUnknown):runtime.publish(account,{},'')
