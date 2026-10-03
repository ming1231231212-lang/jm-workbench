import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from jm_workbench.web.app import create_app
from jm_workbench.community.models import CommunityAccount, CommunityPost
from jm_workbench.community.adapters import NotSubmitted


class FakeCommunity:
    def __init__(self):
        self.sent = []
        self.identity = 'test-user'
        self.fail = None

    def check(self, account, secret):
        return self.identity

    def publish(self, account, secret, payload, destination):
        self.sent.append((account['platform'], payload['title'], destination))
        if self.fail:
            raise self.fail
        return {'post_id': '123', 'url': 'https://dev.to/test-user/test-123', 'visibility': 'unverified'}

    def open(self, account, url):
        return {'message': '已打开账号浏览器'}


@pytest.fixture
def setup(tmp_path):
    bridge = FakeCommunity()
    app = create_app(tmp_path, worker=False, community_adapter=bridge)
    service = app.state.community
    clock = [1000000.0]
    service.clock = lambda: clock[0]
    with TestClient(app, base_url='http://127.0.0.1:8776') as client:
        client.headers['X-JM-Token'] = client.get('/api/state').json()['token']
        yield client, service, bridge, clock


def account(s, platform='dev', name='测试账号'):
    a = s.save_account(CommunityAccount(platform=platform, name=name, identity_hint='test-user', secret='secret-DO-NOT-LEAK'))
    if platform in ('dev', 'x', 'reddit', 'huggingface', 'tieba'):
        s.check_account(a['id'])
    return a['id']


def test_tieba_sync_records_identity_without_jobs_or_risk_reset(setup):
    c,s,b,_=setup
    a=s.save_account(CommunityAccount(platform='tieba',name='待登录'))
    with s.store.connect(True) as db:
        db.execute("INSERT INTO community_risk VALUES('tieba','已有平台限制',1)")
    r=c.post('/api/community/accounts/'+a['id']+'/sync',json={})
    assert r.status_code==200 and r.json()['status']=='verified'
    assert s.account(a['id'])['identity']==b.identity
    assert s.account(a['id'])['checked']>0
    assert not b.sent and not s.state()['posts']
    assert s.state()['risk'][0]['reason']=='已有平台限制'


def test_tieba_sync_waits_for_login_and_rejects_changed_identity(setup):
    _,s,b,_=setup
    a=s.save_account(CommunityAccount(platform='tieba',name='待登录'))
    def pending(*args):raise NotSubmitted('等待贴吧登录')
    original=b.check;b.check=pending
    assert s.sync_account(a['id'])['status']=='pending'
    assert not s.account(a['id'])['identity']
    b.check=original;s.sync_account(a['id'])
    b.identity='another-user'
    result=s.sync_account(a['id'])
    assert result['status']=='pending' and '身份已变化' in result['message']
    assert s.account(a['id'])['identity']=='test-user' and not b.sent


def test_sync_only_enabled_tieba_accounts(setup):
    _,s,b,_=setup
    def unexpected(*args):raise AssertionError('adapter must not be called')
    b.check=unexpected
    for platform,enabled in [('tieba',False),('dev',True)]:
        a=s.save_account(CommunityAccount(platform=platform,name='账号',enabled=enabled))
        with pytest.raises(ValueError):s.sync_account(a['id'])


def test_concurrent_identity_binding_cannot_be_overwritten(setup):
    _,s,b,_=setup
    a=s.save_account(CommunityAccount(platform='tieba',name='并发核验'))
    def raced(*args):
        with s.store.connect(True) as db:
            db.execute('UPDATE community_accounts SET identity=? WHERE id=?',('other-user',a['id']))
        return 'test-user'
    b.check=raced
    with pytest.raises(ValueError,match='身份已变化'):s.check_account(a['id'])
    assert s.account(a['id'])['identity']=='other-user'


def post(s, aid, **changes):
    value = dict(request_id='request-test-00001', title='测试标题', body='本地模拟测试正文', targets=[{'account_id': aid, 'destination': ''}])
    value.update(changes)
    return s.save(CommunityPost(**value))['id']


def test_catalog_and_no_secret_leak(setup):
    c, s, _, _ = setup
    account(s)
    state = c.get('/api/community/state').json()
    assert len(state['platforms']) == 20
    assert sum(p['region'] == '国内' for p in state['platforms']) == 10
    assert 'secret-DO-NOT-LEAK' not in json.dumps(state)
    assert 'secret-DO-NOT-LEAK' not in s.store.path
    assert state['accounts'][0]['secret_configured']


def test_draft_does_not_send_and_launch_idempotent(setup):
    _, s, b, _ = setup
    aid = account(s)
    pid = post(s, aid)
    s.tick()
    assert not b.sent
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: s.launch(pid), range(4)))
    assert len({r['id'] for r in results}) == 1
    s.tick(); s.tick()
    assert len(b.sent) == 1
    assert s.state()['posts'][0]['jobs'][0]['state'] == 'submitted'


def test_dedup_across_drafts_and_same_platform_identity(setup):
    _, s, _, _ = setup
    a = account(s)
    s.launch(post(s, a))
    b = account(s, name='同一身份别名')
    other = post(s, b, request_id='request-test-00002')
    with pytest.raises(ValueError, match='重复'):
        s.launch(other)


def test_unknown_stops_platform_and_never_retries(setup):
    _, s, b, clock = setup
    a = account(s)
    s.launch(post(s, a))
    b.fail = TimeoutError('secret-DO-NOT-LEAK')
    s.tick(); clock[0] += 86401; s.tick()
    assert len(b.sent) == 1
    assert s.state()['posts'][0]['jobs'][0]['state'] == 'unknown'
    assert 'secret-DO-NOT-LEAK' not in json.dumps(s.state())
    with pytest.raises(ValueError, match='暂停|不明|限制'):
        s.launch(post(s, a, request_id='request-test-00003', title='其他标题'))


def test_identity_change_and_config_change_block_send(setup):
    _, s, b, _ = setup
    a = account(s)
    pid = post(s, a)
    s.launch(pid)
    with pytest.raises(ValueError):
        s.save_account(CommunityAccount(platform='dev', name='changed'), a)
    b.identity = 'different-user'
    s.tick()
    assert not b.sent
    assert s.state()['posts'][0]['jobs'][0]['state'] == 'failed'


def test_scheduling_stop_resume_and_cancel(setup):
    _, s, b, clock = setup
    a = account(s)
    pid = post(s, a, schedule_at=clock[0] + 3600)
    s.launch(pid); s.tick()
    assert not b.sent
    s.control(pid, 'pause'); clock[0] += 3601; s.tick()
    assert not b.sent
    s.control(pid, 'resume'); s.tick()
    assert len(b.sent) == 1
    s.control(pid, 'cancel'); s.tick()
    assert len(b.sent) == 1


def test_manual_handoff_never_calls_publisher(setup):
    _, s, b, _ = setup
    a = account(s, 'hackernews')
    pid = post(s, a)
    s.launch(pid); s.tick()
    job = s.state()['posts'][0]['jobs'][0]
    assert job['state'] == 'manual'
    s.open_job(job['id'])
    assert not b.sent
    with pytest.raises(ValueError):
        s.record_url(job['id'], 'https://evil.test/a')
    s.record_url(job['id'], 'https://news.ycombinator.com/item?id=123')
    assert s.state()['posts'][0]['jobs'][0]['state'] == 'recorded'


def test_api_token_and_validation(setup):
    c, s, _, _ = setup
    assert c.post('/api/community/accounts', json={'platform': 'invalid', 'name': 'x'}).status_code == 422
    headers = dict(c.headers)
    c.headers.pop('X-JM-Token')
    assert c.post('/api/community/posts', json={}).status_code == 403
    c.headers.update(headers)
    a = account(s)
    assert c.post('/api/community/posts', json={'request_id': 'api-request-0001', 'title': '标题', 'body': '正文', 'targets': [{'account_id': a}]}).status_code == 200
    assert c.get('/api/community/state').json()['posts'][0]['state'] == 'draft'


def test_restart_running_marks_unknown_without_replay(setup):
    _, s, b, _ = setup
    a = account(s)
    s.launch(post(s, a))
    with s.store.connect(True) as db:
        db.execute("UPDATE community_jobs SET state='running',started=1")
    s.recover(); s.tick()
    assert not b.sent
    assert s.state()['posts'][0]['jobs'][0]['state'] == 'unknown'


def test_platform_budget_shared_between_accounts(setup):
    _, s, b, clock = setup
    a = account(s)
    s.launch(post(s, a)); s.tick()
    another = post(s, a, request_id='request-test-00004', title='第二篇')
    s.launch(another); s.tick()
    assert len(b.sent) == 1
    clock[0] += 1801; s.tick()
    assert len(b.sent) == 2


def test_invalid_target_and_long_title_fail_before_launch(setup):
    _, s, b, _ = setup
    a = account(s, 'reddit')
    pid = post(s, a)
    with pytest.raises(ValueError, match='社区|板块'):
        s.launch(pid)
    assert not b.sent


def test_definite_rejection_is_not_submitted(setup):
    _, s, b, _ = setup
    a = account(s)
    s.launch(post(s, a)); b.fail = NotSubmitted('平台拒绝')
    s.tick()
    assert s.state()['posts'][0]['jobs'][0]['state'] == 'failed'


def test_unknown_resolution_and_unlock_do_not_resend(setup):
    _, s, b, _ = setup
    a=account(s);s.launch(post(s,a));b.fail=TimeoutError();s.tick()
    j=s.state()['posts'][0]['jobs'][0]
    with pytest.raises(ValueError):s.clear_risk('dev','已经检查平台并重新完成登录授权')
    s.resolve(j['id'],'not_sent','已经到平台逐条检查，确认没有发布该帖子','')
    s.clear_risk('dev','已经检查平台并重新完成登录授权')
    s.tick()
    assert len(b.sent)==1 and s.state()['risk']==[]


def test_cancel_during_read_preflight_never_sends(setup):
    _,s,b,_=setup
    a=account(s);pid=post(s,a);s.launch(pid)
    original=b.check
    def stop(*args):
        s.stop_all()
        return original(*args)
    b.check=stop
    s.tick()
    assert b.sent==[]


def test_secret_encrypted_on_disk_and_account_edit_resets_identity(setup):
    _,s,_,_=setup
    a=account(s)
    assert 'secret-DO-NOT-LEAK' not in json.dumps(s.store.rows('SELECT * FROM community_accounts'))
    assert s.account(a)['identity']
    s.save_account(CommunityAccount(platform='dev',name='新名称'),a)
    assert s.account(a)['identity']==''


def test_tieba_title_limits_and_snapshot_destination(setup):
    _,s,b,_=setup
    a=account(s,'tieba')
    pid=post(s,a,title='太短',targets=[{'account_id':a,'destination':'人工智能'}])
    with pytest.raises(ValueError):s.launch(pid)
    pid=post(s,a,request_id='tieba-request-0002',title='这是测试标题文字',targets=[{'account_id':a,'destination':'人工智能'}])
    s.launch(pid)
    j=s.state()['posts'][0]['jobs'][0]
    assert s.job(j['id'])['snapshot']['destination']=='人工智能'


def test_delete_only_selected_unused_account_preserves_profile_and_other_account(setup):
    c,s,b,_=setup
    kept=account(s,'tieba',name='同名账号')
    removed=s.save_account(CommunityAccount(platform='tieba',name='同名账号'))
    before=s.account(kept)
    profile=s.cfg.config.home/'community-profiles'/removed['id']
    profile.mkdir(parents=True);(profile/'login-marker').write_text('preserve')
    with s.store.connect(True) as db:db.execute("INSERT INTO community_risk VALUES('tieba','保留平台暂停',1)")
    path='/api/community/accounts/'+removed['id']+'?version='+str(removed['version'])
    result=c.delete(path)
    assert result.status_code==200 and result.json()['deleted']
    assert [a['id'] for a in s.state()['accounts']]==[kept]
    assert s.account(kept)==before and (profile/'login-marker').read_text()=='preserve'
    assert s.state()['risk'][0]['reason']=='保留平台暂停' and not b.sent
    assert c.delete(path).status_code==200 # A repeat after a lost response is harmless.


@pytest.mark.parametrize('state',['queued','running','paused','unknown','manual','submitted','failed','not_sent','cancelled','recorded'])
def test_delete_rejects_any_job_reference_and_keeps_history(setup,state):
    c,s,_,_=setup
    aid=account(s)
    with s.store.connect(True) as db:
        db.execute('INSERT INTO community_jobs(id,account_id,state) VALUES(?,?,?)',('referenced-job',aid,state))
    before=s.store.rows('SELECT * FROM community_jobs')
    result=c.delete('/api/community/accounts/'+aid+'?version=1')
    assert result.status_code==400 and '停用' in result.json()['error']
    assert s.account(aid) and s.store.rows('SELECT * FROM community_jobs')==before


def test_delete_rejects_post_reference_until_draft_target_is_changed(setup):
    _,s,_,_=setup
    aid=account(s);other=account(s,name='保留账号');pid=post(s,aid)
    with pytest.raises(ValueError,match='帖子|草稿'):s.delete_account(aid,1)
    draft=s.state()['posts'][0]['payload'];draft['targets']=[{'account_id':other,'destination':''}]
    s.save(CommunityPost(**draft),pid)
    s.delete_account(aid,1)
    assert s.state()['posts'][0]['payload']['targets'][0]['account_id']==other


def test_delete_requires_token_version_and_rejects_stale_confirmation(setup):
    c,s,_,_=setup
    aid=account(s);path='/api/community/accounts/'+aid
    assert c.delete(path).status_code==422
    token=c.headers.pop('X-JM-Token')
    assert c.delete(path+'?version=1').status_code==403
    c.headers['X-JM-Token']=token
    s.save_account(CommunityAccount(platform='dev',name='用户已修改'),aid)
    assert c.delete(path+'?version=1').status_code==400
    assert s.account(aid)['name']=='用户已修改'


def test_pending_edit_and_login_check_cannot_recreate_deleted_account(setup):
    _,s,b,_=setup
    aid=account(s)
    def delete_during_check(*args):
        s.delete_account(aid,1)
        return b.identity
    b.check=delete_during_check
    with pytest.raises(ValueError,match='改变'):s.check_account(aid)
    with pytest.raises(ValueError,match='不存在'):s.save_account(CommunityAccount(platform='dev',name='旧编辑'),aid)
    assert not s.state()['accounts']


def test_account_delete_racing_draft_save_never_leaves_dangling_target(setup):
    import threading
    _,s,_,_=setup
    aid=account(s);barrier=threading.Barrier(2)
    def run(action):
        barrier.wait()
        try:return action()
        except ValueError:return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(run,lambda:s.delete_account(aid,1))
        second=pool.submit(run,lambda:post(s,aid))
        first.result();second.result()
    accounts=s.state()['accounts'];posts=s.state()['posts']
    assert (len(accounts),len(posts)) in [(0,0),(1,1)]
