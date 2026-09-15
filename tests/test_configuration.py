from pathlib import Path
import pytest
from jm_workbench.core.config import Config
from jm_workbench.core.db import Store
from jm_workbench.services.configuration import Configuration

@pytest.fixture
def cfg(tmp_path, monkeypatch):
    c = Configuration(Config(tmp_path), Store(tmp_path / 'jm.db'))
    monkeypatch.setattr('jm_workbench.services.configuration.endpoint', lambda _: 'ws://127.0.0.1:1234/test')
    monkeypatch.setattr(c.config, 'crawler_ready', lambda: True)
    return c

def setup_pair(cfg, platform='ks'):
    a = cfg.account(dict(name='账号', platform=platform))
    a = cfg.store.put('account', dict(a, connection='connected'), a['id'])
    t = cfg.task(dict(name='爬虫', platform=platform, kind='crawler', keywords=['关键词']))
    cfg.binding(dict(task_id=t['id'], account_id=a['id']))
    return a, t

def test_profile_and_platform_isolation(cfg):
    a, t = setup_pair(cfg)
    with pytest.raises(ValueError, match='资料'):
        cfg.account(dict(name='重复', platform='dy', profile_dir=a['profile_dir']))
    other = cfg.account(dict(name='其他', platform='dy'))
    with pytest.raises(ValueError, match='不一致'):
        cfg.binding(dict(task_id=t['id'], account_id=other['id']))

def test_one_click_is_idempotent_and_freezes_config(cfg):
    a, t = setup_pair(cfg)
    first = cfg.launch()
    assert first['ok'] and len(first['created']) == 1
    assert cfg.launch()['existing'] == first['created']
    with pytest.raises(ValueError, match='先停止'):
        cfg.task(dict(name='修改', platform='ks', kind='crawler', keywords=['新词']), t['id'])
    with pytest.raises(ValueError, match='先停止'):
        cfg.binding(dict(task_id=t['id'], account_id=a['id'], enabled=False))
    cfg.store.stop()
    cfg.task(dict(name='修改', platform='ks', kind='crawler', keywords=['新词']), t['id'])

def test_preflight_is_all_or_nothing(cfg):
    setup_pair(cfg)
    a, _ = setup_pair(cfg, 'dy')
    cfg.store.put('account', dict(a, connection='unverified'), a['id'])
    assert not cfg.launch()['ok']
    assert not cfg.store.rows('SELECT * FROM runs')

def test_risk_applies_to_all_platform_accounts(cfg):
    setup_pair(cfg)
    cfg.store.lock('ks', '平台 HTTP 429')
    assert '限制' in cfg.launch()['errors'][0]['reason']
