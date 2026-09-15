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
    t = cfg.task(dict(platform='ks', kind='adult_comments', **DEFAULTS['adult_comments']))
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
