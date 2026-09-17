import json
from datetime import datetime
from types import SimpleNamespace
import pytest
from jm_workbench.core.config import Config
from jm_workbench.core.db import Store
from jm_workbench.policies.rules import DEFAULTS
from jm_workbench.services.configuration import Configuration
from jm_workbench.services.engine import Engine
from jm_workbench.services.guard import CN, reserve, finish, recover, read_slot
from jm_workbench.adapters.errors import PlatformRisk
from jm_workbench.adapters.crawler_child import response_risk


@pytest.fixture
def rig(tmp_path, monkeypatch):
    clock = SimpleNamespace(now=datetime(2026, 9, 15, 20, tzinfo=CN).timestamp())
    item = dict(video_id='video1234', author_id='author1234', caption='本店成人用品库存清仓', nickname='商家',
                detail_verified=True, can_comment=True, source={'kind': 'detail'})
    class Fake:
        sends = 0
        receipt = {'ok': True, 'comment_id': 'receipt123', 'reason': '已返回ID，可见性未核验'}
        identity = 'account1234'
        def __init__(self, _): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def account(self): return {'id': self.identity}
        def search(self, keyword): return [dict(item, detail_verified=False)]
        def detail(self, vid): return dict(item, observed_at=clock.now)
        def send(self, expected, text):
            Fake.sends += 1
            return self.receipt
    cfg = Configuration(Config(tmp_path), Store(tmp_path/'jm.db'), Fake)
    monkeypatch.setattr('jm_workbench.services.configuration.endpoint', lambda _: 'ws://127.0.0.1:1234/test')
    monkeypatch.setattr(cfg.config, 'crawler_ready', lambda: True)
    a = cfg.account(dict(name='账号', platform='ks'))
    a = cfg.store.put('account', dict(a, connection='verified', identity='account1234'), a['id'])
    t = cfg.task(dict(platform='ks', kind='adult_comments', publish_scope='limited', **DEFAULTS['adult_comments']))
    cfg.binding(dict(task_id=t['id'], account_id=a['id']))
    run_id = cfg.launch()['created'][0]
    e = Engine(cfg, clock=lambda: clock.now)
    return SimpleNamespace(cfg=cfg, store=cfg.store, engine=e, clock=clock, fake=Fake, run_id=run_id, item=item)

def advance(rig, seconds=301):
    rig.clock.now += seconds
    rig.engine.tick()

def test_exact_target_pipeline_and_success_receipt(rig):
    rig.engine.tick()
    assert rig.fake.sends == 0
    advance(rig)
    assert rig.fake.sends == 1
    assert rig.store.rows('SELECT state FROM attempts')[0]['state'] == 'sent'
    assert rig.store.rows('SELECT state FROM runs')[0]['state'] == 'completed'
    assert len(rig.store.rows('SELECT * FROM evidence')) == 2

def test_unknown_receipt_stops_platform_and_never_retries(rig):
    rig.fake.receipt = {'uncertain': True, 'reason': '网络超时'}
    rig.engine.tick()
    advance(rig)
    assert rig.fake.sends == 1
    assert rig.store.rows('SELECT * FROM risk')[0]['platform'] == 'ks'
    advance(rig, 3600)
    assert rig.fake.sends == 1
    assert not rig.cfg.launch()['ok']

def test_switched_account_cannot_send(rig):
    rig.fake.identity = 'differentaccount'
    rig.engine.tick()
    assert rig.fake.sends == 0
    assert rig.store.rows('SELECT state FROM runs')[0]['state'] == 'paused'
    assert not rig.store.rows('SELECT * FROM risk')

def test_stop_before_detail_prevents_any_send(rig):
    rig.engine.tick()
    rig.store.stop()
    advance(rig)
    assert rig.fake.sends == 0

def test_historical_video_contact_blocks_new_task(rig):
    with rig.store.connect() as db:
        db.execute('INSERT INTO history VALUES(?,?,?,?,?)', ('ks', 'video1234', 'author1234', '旧评论', 0))
    rig.engine.tick()
    advance(rig)
    assert rig.fake.sends == 0
    assert not rig.store.rows('SELECT * FROM attempts')

def test_restart_reservation_stays_unknown(rig):
    with rig.store.connect() as db:
        db.execute("INSERT INTO attempts(id,platform,video_id,state,created) VALUES('x','ks','v','reserved',?)", (rig.clock.now,))
    recover(rig.store)
    assert rig.store.rows('SELECT state FROM attempts')[0]['state'] == 'unknown'
    assert rig.store.rows('SELECT * FROM risk')

def test_reads_share_budget_across_accounts(rig):
    assert read_slot(rig.store, 'ks', rig.clock.now) == rig.clock.now
    assert read_slot(rig.store, 'ks', rig.clock.now) == rig.clock.now + 300
    assert read_slot(rig.store, 'dy', rig.clock.now) == rig.clock.now

def test_no_detail_permission_no_comment(rig):
    rig.item['can_comment'] = False
    rig.engine.tick()
    advance(rig)
    assert rig.fake.sends == 0

def test_business_change_in_detail_no_comment(rig):
    rig.engine.tick()
    rig.item['caption'] = '旅游的快乐生活'
    advance(rig)
    assert rig.fake.sends == 0

@pytest.mark.parametrize('status,data', [(403, {}), (429, {}), (200, {'msg': '操作频繁'}), (200, {'result': 400002}), (471, {})])
def test_crawler_risk_does_not_retry(status, data):
    assert response_risk(status, data)

def test_crawler_success_payload():
    assert response_risk(200, {'result': 1, 'data': []}) == ''


def configure_generated_run(rig):
    from jm_workbench.policies.comments import ADULT_CORE
    rig.store.stop()
    old=rig.store.objects('task')[0]
    payload={k:v for k,v in old.items() if k not in ('id','version')}
    task=rig.cfg.task(dict(payload,adult_target='merchant',comment_mode='core_variants',comment_core=ADULT_CORE),old['id'])
    rig.run_id=rig.cfg.launch()['created'][0]
    rig.item['caption']='本店成人用品正常营业'
    return task


def test_generated_merchant_comment_reaches_reservation_and_fake_send(rig):
    from jm_workbench.policies.comments import candidates
    task=configure_generated_run(rig)
    rig.engine.tick()
    advance(rig)
    assert rig.fake.sends==1
    attempt=rig.store.rows('SELECT * FROM attempts')[0]
    assert attempt['content']==candidates(task,rig.item)[0]
    assert attempt['state']=='sent'


def test_generated_comment_does_not_reroll_to_avoid_contact_history(rig):
    from jm_workbench.policies.comments import candidates
    task=configure_generated_run(rig)
    with rig.store.connect() as db:
        db.execute('INSERT INTO history VALUES(?,?,?,?,?)',('ks','other-video','other-author',candidates(task,rig.item)[0],rig.clock.now-2000))
    rig.engine.tick()
    advance(rig)
    assert rig.fake.sends==0
    assert not rig.store.rows('SELECT * FROM attempts')


def test_generated_comment_unknown_result_still_locks_platform(rig):
    configure_generated_run(rig)
    rig.fake.receipt={'uncertain':True,'reason':'模拟网络中断'}
    rig.engine.tick()
    advance(rig)
    advance(rig,3600)
    assert rig.fake.sends==1
    assert rig.store.rows('SELECT * FROM risk')


def configure_keyword_run(rig):
    task=configure_generated_run(rig)
    rig.store.stop()
    payload={k:v for k,v in task.items() if k not in ('id','version')}
    task=rig.cfg.task(dict(payload,adult_target='keyword',keywords=['成人用品店怎么样']),task['id'])
    rig.run_id=rig.cfg.launch()['created'][0]
    rig.item.update(caption='记者调查：成人用品店经营情况',nickname='城市新闻')
    rig.fake.search=lambda self,keyword:[dict(rig.item,detail_verified=False,source={'kind':'search','query':keyword})]
    return task


def test_keyword_search_origin_survives_detail_and_reservation(rig):
    task=configure_keyword_run(rig)
    rig.engine.tick()
    row=rig.store.rows('SELECT progress FROM runs WHERE id=?',(rig.run_id,))[0]
    pending=json.loads(row['progress'])['pending'][0]
    assert pending['search_origin']['query']==task['keywords'][0]
    advance(rig)
    assert rig.fake.sends==1
    item=json.loads(rig.store.rows('SELECT evidence FROM attempts')[0]['evidence'])
    assert item['search_origin']['video_id']==item['video_id']
    assert item['search_origin']['query']==task['keywords'][0]


def test_keyword_mode_rechecks_actual_detail_topic(rig):
    configure_keyword_run(rig)
    rig.engine.tick()
    rig.item['caption']='今天女装店换新款'
    advance(rig)
    assert rig.fake.sends==0
    assert not rig.store.rows('SELECT * FROM attempts')


def test_keyword_mode_rejects_mislabeled_search_response(rig):
    configure_keyword_run(rig)
    rig.fake.search=lambda self,keyword:[dict(rig.item,source={'kind':'search','query':'另一个词'})]
    rig.engine.tick()
    advance(rig)
    assert rig.fake.sends==0
    assert rig.store.rows('SELECT decision FROM evidence')[0]['decision']=='skipped'


@pytest.fixture
def batch(rig):
    """Six search matches: first sent, five left, as in the reported regression."""
    from jm_workbench.policies.comments import candidates
    task = configure_keyword_run(rig)
    items, texts = [], set()
    for i in range(200):
        item = dict(rig.item, video_id=f'video{i:04}', author_id=f'author{i:04}',
                    source={'kind': 'search', 'query': task['keywords'][0]})
        text = candidates(task, item)[0]
        if text not in texts:
            texts.add(text)
            items.append(item)
        if len(items) == 6:
            break
    assert len(items) == 6
    rig.fake.search = lambda self, keyword: items
    def detail(self, vid):
        item = next(item for item in items if item['video_id'] == vid)
        return dict(item, source={'kind': 'detail'}, detail_verified=True, observed_at=rig.clock.now)
    rig.fake.detail = detail
    rig.engine.tick()
    advance(rig)
    original = rig.store.rows('SELECT * FROM runs WHERE id=?', (rig.run_id,))[0]
    assert original['state'] == 'completed' and rig.fake.sends == 1
    assert len(json.loads(original['progress'])['pending']) == 5
    task = rig.cfg.task({k:v for k,v in dict(task, publish_scope='all_matches', comments_per_video=1).items()
                         if k not in ('id','version')}, task['id'])
    rig.items, rig.task, rig.original = items, task, original
    return rig


def continue_batch(batch):
    from jm_workbench.services.continuation import continue_pending
    result = continue_pending(batch.cfg, batch.run_id, batch.clock.now)
    assert result['created']
    return result['run_id']


def row_for(batch, ident):
    row = batch.store.rows('SELECT * FROM runs WHERE id=?', (ident,))[0]
    row['progress'] = json.loads(row['progress'])
    return row


def run_when_due(batch, ident):
    row = row_for(batch, ident)
    batch.clock.now = max(batch.clock.now, row['due'])
    assert batch.engine.tick()
    return row_for(batch, ident)


def test_all_matches_keeps_queue_after_first_and_rolls_daily_budget(batch):
    from jm_workbench.services.guard import recover
    child = continue_batch(batch)
    batch.fake.search = lambda *args: pytest.fail('续接不能重新搜索')
    for expected in range(2, 6):
        row = run_when_due(batch, child)
        assert batch.fake.sends == expected
        assert row['state'] == 'waiting'
        assert len(row['progress']['pending']) == 6-expected
    row = run_when_due(batch, child)
    assert batch.fake.sends == 5 and row['state'] == 'waiting'
    assert row['due'] - batch.clock.now > 12*3600
    recover(batch.store)
    batch.engine = Engine(batch.cfg, clock=lambda: batch.clock.now)
    row = run_when_due(batch, child)
    assert batch.fake.sends == 6 and row['state'] == 'completed'
    assert not row['progress']['pending'] and row['progress']['sent'] == 5
    assert len({r['video_id'] for r in batch.store.rows('SELECT * FROM attempts')}) == 6
    assert batch.store.rows('SELECT * FROM runs WHERE id=?', (batch.run_id,))[0] == batch.original


def test_continuation_skips_contacted_video_and_defers_author_without_blocking_others(batch):
    first, second = batch.items[1:3]
    with batch.store.connect() as db:
        db.execute('INSERT INTO history VALUES(?,?,?,?,?)', ('ks', first['video_id'], first['author_id'], '旧记录', 0))
        db.execute('INSERT INTO history VALUES(?,?,?,?,?)', ('ks', 'another123', second['author_id'], '旧作者', batch.clock.now-3600))
    child = continue_batch(batch)
    row = row_for(batch, child)
    assert row['progress']['imported_count'] == 4 and row['progress']['skipped'] == 1
    assert row['progress']['pending'][0]['not_before'] > batch.clock.now + 6*86400
    row = run_when_due(batch, child)
    assert batch.fake.sends == 2
    assert len(row['progress']['pending']) == 3
    assert row['progress']['pending'][0]['video_id'] == second['video_id']
    assert batch.store.rows('SELECT video_id FROM attempts ORDER BY created DESC')[0]['video_id'] == batch.items[3]['video_id']
    # Freeze all but the deferred target and advance to expiry; it is revalidated and sent.
    row['progress']['pending'] = row['progress']['pending'][:1]
    with batch.store.connect() as db:
        db.execute('UPDATE runs SET progress=? WHERE id=?', (json.dumps(row['progress']), child))
    row = run_when_due(batch, child)
    assert row['state'] == 'waiting' and batch.fake.sends == 2
    row = run_when_due(batch, child)
    assert row['state'] == 'completed' and batch.fake.sends == 3


def test_new_contact_after_queueing_is_deferred_not_lost(batch):
    child = continue_batch(batch)
    item = batch.items[1]
    with batch.store.connect() as db:
        db.execute('INSERT INTO history VALUES(?,?,?,?,?)', ('ks','different123',item['author_id'],'历史评论',batch.clock.now))
    row = run_when_due(batch, child)
    assert batch.fake.sends == 1 and len(row['progress']['pending']) == 5
    assert row['progress']['pending'][0]['not_before'] > batch.clock.now
    run_when_due(batch, child)  # read interval
    run_when_due(batch, child)
    assert batch.fake.sends == 2


def test_continuation_idempotent_under_simultaneous_requests(batch):
    from concurrent.futures import ThreadPoolExecutor
    from jm_workbench.services.continuation import continue_pending
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: continue_pending(batch.cfg, batch.run_id, batch.clock.now), range(3)))
    assert sum(r['created'] for r in results) == 1
    assert len({r['run_id'] for r in results}) == 1
    assert len(batch.store.rows('SELECT * FROM continuations')) == 1
    assert batch.fake.sends == 1


def test_stopped_continuation_can_continue_without_losing_search_evidence(batch):
    from jm_workbench.services.continuation import continue_pending
    child = continue_batch(batch)
    batch.store.stop(child)
    result = continue_pending(batch.cfg, child, batch.clock.now)
    assert result['queued'] == 5 and result['skipped'] == []
    assert batch.fake.sends == 1


@pytest.mark.parametrize('block', ['risk', 'unknown', 'identity', 'keyword', 'origin'])
def test_continuation_refuses_unsafe_or_unproven_targets(batch, block):
    from jm_workbench.services.continuation import continue_pending
    if block == 'risk':
        batch.store.lock('ks', '平台限制')
    elif block == 'unknown':
        with batch.store.connect() as db:
            db.execute("INSERT INTO attempts(id,platform,video_id,state,created) VALUES('u','ks','unknown123','unknown',?)", (batch.clock.now,))
    elif block == 'identity':
        account = batch.store.objects('account')[0]
        batch.store.put('account', dict(account, identity='changed123'), account['id'])
    elif block == 'keyword':
        batch.cfg.task({k:v for k,v in dict(batch.task, keywords=['情趣用品店']).items() if k not in ('id','version')}, batch.task['id'])
    elif block == 'origin':
        with batch.store.connect() as db:
            db.execute('DELETE FROM evidence WHERE run_id=?', (batch.run_id,))
    if block in ('keyword','origin'):
        result = continue_pending(batch.cfg, batch.run_id, batch.clock.now)
        assert result['queued'] == 0 and len(result['skipped']) == 5
    else:
        with pytest.raises(ValueError):
            continue_pending(batch.cfg, batch.run_id, batch.clock.now)
        assert not batch.store.rows('SELECT * FROM continuations')
    assert batch.fake.sends == 1


def test_continuation_api_requires_token_and_reports_link(batch):
    from fastapi.testclient import TestClient
    from jm_workbench.web.app import create_app
    with TestClient(create_app(batch.cfg.config.home, worker=False, configuration=batch.cfg), base_url='http://127.0.0.1:8776') as client:
        url = '/api/runs/'+batch.run_id+'/continue'
        assert client.post(url, json={}).status_code == 403
        client.headers['X-JM-Token'] = client.get('/api/state').json()['token']
        response = client.post(url, json={})
        assert response.status_code == 200 and response.json()['queued'] == 5
        assert client.post(url, json={}).json()['created'] is False
        source = next(r for r in client.get('/api/state').json()['runs'] if r['id'] == batch.run_id)
        assert source['continuation_id'] == response.json()['run_id']
        assert batch.fake.sends == 1


def test_per_video_quantity_and_legacy_scope_are_explicit(rig):
    from jm_workbench.core.models import TaskInput
    from jm_workbench.services.engine import publish_limit_reached
    payload = dict(platform='ks', kind='adult_comments', **DEFAULTS['adult_comments'])
    task = TaskInput.model_validate(payload).model_dump()
    assert task['comments_per_video'] == 1 and task['publish_scope'] == 'all_matches'
    assert not publish_limit_reached(task, {'sent': 1})
    assert publish_limit_reached({'max_publish': 1}, {'sent': 1})
    with pytest.raises(ValueError):
        TaskInput.model_validate(dict(payload, comments_per_video=2))


def test_continuation_detail_error_preserves_target_and_unknown_send_never_retries(batch):
    from jm_workbench.adapters.errors import LocalBrowserError
    from jm_workbench.services.continuation import continue_pending
    child = continue_batch(batch)
    original_detail = batch.fake.detail
    def disconnected(*args):
        raise LocalBrowserError('模拟本机断开')
    batch.fake.detail = disconnected
    row = run_when_due(batch, child)
    assert row['state'] == 'paused' and len(row['progress']['pending']) == 5
    batch.fake.detail = original_detail
    next_child = continue_pending(batch.cfg, child, batch.clock.now)['run_id']
    batch.fake.receipt = {'uncertain': True, 'reason': '模拟未知回执'}
    run_when_due(batch, next_child)
    run_when_due(batch, next_child)
    assert batch.fake.sends == 2
    assert row_for(batch, next_child)['state'] == 'paused'
    with pytest.raises(ValueError):
        continue_pending(batch.cfg, next_child, batch.clock.now)
    assert batch.fake.sends == 2
