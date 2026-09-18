import json
from types import SimpleNamespace

import pytest

from jm_workbench.core.db import Store
from jm_workbench.core.instance import InstanceLock
from scripts import service_watchdog as module


@pytest.fixture
def watchdog(tmp_path, monkeypatch):
    clock = SimpleNamespace(now=1000)
    config = tmp_path/'service-watchdog.json'
    module.atomic_json(config, {'version':1,'port':8776,'poll_seconds':30,'app_revision':'test-revision'})
    store = Store(tmp_path/'jm.db')
    with store.connect() as db:
        db.execute("INSERT INTO risk VALUES('ks','平台限制必须保留',1)")
        db.execute("INSERT INTO runs(id,state,progress) VALUES('paused','paused','{}')")
        db.execute("INSERT INTO attempts(id,platform,video_id,state,created) VALUES('u','ks','unknown1','unknown',1)")
    monkeypatch.setattr(module, 'revision', lambda:'test-revision')
    monkeypatch.setattr(module, 'health', lambda port:None)
    monkeypatch.setattr(module, 'port_open', lambda port:False)
    w = module.Watchdog(config, clock=lambda:clock.now, sleep=lambda seconds:None)
    w.spawn = lambda port:pytest.fail('不得启动额外服务')
    return SimpleNamespace(w=w,clock=clock,store=store,config=config)


def healthy():
    return {'app_id':'jm-workbench','revision':'test-revision','worker':True}


def business_state(store):
    return {table:store.rows('SELECT * FROM '+table) for table in ('runs','attempts','risk','events','reads','objects')}


def test_healthy_check_never_restarts_or_changes_paused_business(watchdog,monkeypatch):
    b=watchdog
    monkeypatch.setattr(module,'health',lambda port:healthy())
    before=business_state(b.store)
    assert b.w.step()['status']=='healthy'
    b.clock.now+=30
    assert b.w.step()['checked_at']==1030
    assert business_state(b.store)==before
    assert json.loads(b.w.state_path.read_text(encoding='utf-8'))['watchdog_pid']>0


def test_stopped_service_starts_once_and_keeps_risk_unknown_and_paused_records(watchdog,monkeypatch):
    b=watchdog
    before=business_state(b.store)
    calls=[]
    def spawn(port):
        calls.append(port)
        monkeypatch.setattr(module,'health',lambda port:healthy())
        return SimpleNamespace(pid=123,poll=lambda:None)
    b.w.spawn=spawn
    assert b.w.step()['status']=='recovered'
    assert calls==[8776]
    assert business_state(b.store)==before
    b.clock.now+=30
    assert b.w.step()['status']=='healthy' and calls==[8776]


@pytest.mark.parametrize('response',[{'app_id':'other'},dict(app_id='jm-workbench',worker=False,revision='test-revision'),dict(app_id='jm-workbench',worker=True,revision='old')])
def test_wrong_service_never_killed_or_replaced(watchdog,monkeypatch,response):
    monkeypatch.setattr(module,'health',lambda port:response)
    assert watchdog.w.step()['status']=='occupied_or_unhealthy'


def test_port_occupied_but_http_unresponsive_is_not_replaced(watchdog,monkeypatch):
    monkeypatch.setattr(module,'port_open',lambda port:True)
    assert watchdog.w.step()['status']=='occupied_or_unhealthy'


def test_existing_worker_lock_blocks_second_process(watchdog):
    lock=InstanceLock(watchdog.w.home/'worker.lock')
    try:
        assert watchdog.w.step()['status']=='worker_busy'
    finally:
        lock.close()


def test_maintenance_disable_and_code_change_block_restart(watchdog,monkeypatch):
    b=watchdog
    disabled=b.w.home/'service-watchdog.disabled'
    disabled.write_text('maintenance')
    assert b.w.step()['status']=='disabled'
    disabled.unlink()
    monkeypatch.setattr(module,'revision',lambda:'changed')
    assert b.w.step()['status']=='revision_changed'


def test_missing_original_database_is_not_silently_recreated(watchdog):
    watchdog.store=None
    (watchdog.w.home/'jm.db').unlink()
    assert watchdog.w.step()['status']=='missing_database'
    assert not (watchdog.w.home/'jm.db').exists()


def test_restart_backoff_persists_across_checker_restart_and_caps_at_five_minutes(watchdog):
    b=watchdog
    calls=[]
    def failing(port):
        calls.append(port)
        raise OSError('模拟启动失败')
    b.w.spawn=failing
    for expected_delay in (30,60,120,240,300,300):
        now=b.clock.now
        assert b.w.step()['status']=='start_failed'
        assert b.w.state['next_restart_at']==now+expected_delay
        restarted=module.Watchdog(b.config,clock=lambda:b.clock.now,sleep=lambda _:None)
        restarted.spawn=failing
        b.w=restarted
        b.clock.now=now+expected_delay-1
        assert b.w.step()['status']=='backoff'
        b.clock.now+=1
    assert len(calls)==6


def test_flapping_service_does_not_reset_backoff_until_stable(watchdog,monkeypatch):
    b=watchdog
    b.w.state.update(consecutive_restarts=4,next_restart_at=1200)
    monkeypatch.setattr(module,'health',lambda port:healthy())
    b.w.step()
    b.clock.now+=60
    assert b.w.step()['consecutive_restarts']==4
    b.clock.now+=61
    assert b.w.step()['consecutive_restarts']==0


def test_second_checker_exits_without_actions(watchdog,monkeypatch):
    lock=InstanceLock(watchdog.w.home/'service-watchdog.lock')
    monkeypatch.setattr('sys.argv',['service_watchdog','--config',str(watchdog.config),'--once'])
    monkeypatch.setattr(module.Watchdog,'step',lambda _:pytest.fail('已有检查器时不能重复检查'))
    try:
        module.main()
    finally:
        lock.close()


def test_configuration_requires_verified_existing_worker(watchdog,monkeypatch):
    monkeypatch.setattr('sys.argv',['service_watchdog','--config',str(watchdog.config),'--configure'])
    original=watchdog.config.read_bytes()
    with pytest.raises(ValueError,match='核验'):
        module.main()
    assert watchdog.config.read_bytes()==original
    monkeypatch.setattr(module,'health',lambda port:healthy())
    module.main()
    assert json.loads(watchdog.config.read_text())['app_revision']=='test-revision'
