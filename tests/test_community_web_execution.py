import json
import pytest
from fastapi.testclient import TestClient
from jm_workbench.web.app import create_app
from jm_workbench.community.models import CommunityAccount, CommunityPost, DailyPlan
from jm_workbench.community.adapters import CommunityAdapter, PreflightStopped


class NoBrowser:
    def check(self, *args): raise AssertionError('browser must not be checked')
    def publish(self, *args): raise AssertionError('browser must not submit')
    def ensure_connection(self, *args): raise AssertionError('browser must not connect')
    def open(self, account, url): return {'url': url, 'message': 'opened'}


def setup_web(tmp_path):
    app=create_app(tmp_path, worker=False, community_adapter=NoBrowser())
    s=app.state.community
    s.cfg.config.save({'community_browser_execution':'web'})
    a=s.save_account(CommunityAccount(platform='tieba',name='original account'))
    return app,s,a


def draft(s,a,request_id='web-execution-draft'):
    return s.save(CommunityPost(request_id=request_id,title='趣造AI一起使用',body='一起使用 quzaoai.com，分享实际的AI工具经验。',targets=[{'account_id':a['id'],'destination':'人工智能'}]))['id']


def test_removing_extension_makes_runtime_capabilities_truthful_and_drafts_usable(tmp_path):
    _,s,a=setup_web(tmp_path)
    data=s.state();p=next(p for p in data['platforms'] if p['id']=='tieba')
    assert not p['automatic'] and not p['capabilities']['daily_plan']
    assert data['accounts'][0]['automatic_execution'] is False
    with pytest.raises(ValueError,match='网页发布'):s.check_account(a['id'])
    post=draft(s,a);s.launch(post);s.tick()
    j=s.jobs(post)[0];assert j['state']=='manual' and j['started']==0
    assert '人工智能' in s.open_job(j['id'])['url'] or '%E4%BA%BA' in s.open_job(j['id'])['url']
    s.record_url(j['id'],'https://tieba.baidu.com/p/123456789')
    assert s.jobs(post)[0]['state']=='recorded'
    assert s.state()['summary']['thread_submitted']==0


def test_real_adapter_web_mode_refuses_all_browser_calls_without_touching_transport(tmp_path,monkeypatch):
    _,s,a=setup_web(tmp_path);adapter=CommunityAdapter(s.cfg.config)
    def forbidden(*args):pytest.fail('legacy browser or extension accessed')
    monkeypatch.setattr('jm_workbench.community.adapters.endpoint',forbidden)
    monkeypatch.setattr('jm_workbench.community.adapters.connect_relay',forbidden)
    monkeypatch.setattr('jm_workbench.community.adapters.relay_connection',forbidden)
    for call in (lambda:adapter.ensure_connection(a),lambda:adapter.connect_browser(None,a),lambda:adapter.check(a,''),lambda:adapter.discover(a,[]),lambda:adapter.publish(a,'',{},'')):
        with pytest.raises(PreflightStopped,match='网页发布'):call()


def paused_job(s,a):
    post=draft(s,a);s.launch(post);j=s.jobs(post)[0]
    with s.store.connect(True) as db:db.execute("UPDATE community_jobs SET state='paused' WHERE id=?",(j['id'],))
    return j['id']


def test_only_explicit_proven_unsent_job_can_switch_to_web_without_new_snapshot(tmp_path):
    app,s,a=setup_web(tmp_path);ident=paused_job(s,a)
    before=s.job(ident)
    with TestClient(app,base_url='http://127.0.0.1:8776') as c:
        c.headers['X-JM-Token']=c.get('/api/state').json()['token']
        assert c.post('/api/community/jobs/'+ident+'/web',json={}).status_code==200
    after=s.job(ident)
    assert after['state']=='manual' and after['snapshot']==before['snapshot']
    assert after['identity']==before['identity'] and after['digest']==before['digest']
    assert len(s.jobs(before['post_id']))==1
    assert s.switch_to_web(ident)['message']


@pytest.mark.parametrize('state,started,receipt,risk',[
    ('unknown',0,{},False),('running',1,{},False),('submitted',1,{'url':'https://tieba.baidu.com/p/123'},False),
    ('paused',1,{},False),('paused',0,{'submitted':None},False),('paused',0,{},True),
])
def test_switch_to_web_cannot_bypass_uncertain_receipts_or_platform_risk(tmp_path,state,started,receipt,risk):
    _,s,a=setup_web(tmp_path);ident=paused_job(s,a)
    with s.store.connect(True) as db:
        db.execute('UPDATE community_jobs SET state=?,started=?,receipt=? WHERE id=?',(state,started,json.dumps(receipt),ident))
        if risk:db.execute("INSERT INTO community_risk VALUES('tieba','platform restriction',1)")
    with pytest.raises(ValueError):s.switch_to_web(ident)
    assert s.job(ident)['state']==state


def test_web_mode_pauses_existing_queue_before_browser_or_started_marker(tmp_path):
    _,s,a=setup_web(tmp_path);ident=paused_job(s,a)
    with s.store.connect(True) as db:db.execute("UPDATE community_jobs SET state='queued' WHERE id=?",(ident,))
    s.tick();j=s.job(ident)
    assert j['state']=='paused' and j['started']==0 and '网页发布' in j['message']


def test_web_mode_does_not_enable_daily_sending_or_ignore_platform_risk(tmp_path):
    _,s,a=setup_web(tmp_path)
    plan=s.daily.save(DailyPlan(name='daily',account_id=a['id'],board='人工智能',rules_note='只在相关社区发布原创内容并遵守社区规定'))['id']
    with pytest.raises(ValueError,match='网页发布'):s.daily.control(plan,'enable')
    assert s.daily.state()[0]['next_action_at']==0
    with s.store.connect(True) as db:db.execute("INSERT INTO community_risk VALUES('tieba','platform restriction',1)")
    with pytest.raises(ValueError):s.launch(draft(s,a))
