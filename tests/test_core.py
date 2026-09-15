import pytest
from jm_workbench import APP_NAME
from jm_workbench.core.config import Config, revision
from jm_workbench.core.db import Store
from jm_workbench.core.models import AccountInput, TaskInput
from jm_workbench.core.platforms import PLATFORMS


def test_brand_and_platform_contract():
    assert APP_NAME == 'JM工作台'
    assert len(PLATFORMS) == 7
    assert [p for p, v in PLATFORMS.items() if v['comment']] == ['ks']
    assert len(revision()) == 16


def test_private_config_survives_restart(tmp_path):
    cfg = Config(tmp_path)
    cfg.save({'crawler_root': 'missing'})
    assert Config(tmp_path).values['crawler_root'] == 'missing'
    assert not cfg.crawler_ready()


def test_store_versions_and_rollback(tmp_path):
    s = Store(tmp_path / 'jm.db')
    obj = s.put('account', {'name': '测试'})
    assert s.put('account', {'name': '修改'}, obj['id'])['version'] == 2
    with pytest.raises(RuntimeError):
        with s.connect(True) as db:
            db.execute('DELETE FROM objects')
            raise RuntimeError()
    assert len(s.objects('account')) == 1


def test_invalid_configuration_rejected():
    with pytest.raises(ValueError):
        AccountInput(name='x', platform='unknown')
    with pytest.raises(ValueError):
        TaskInput(name='x', platform='dy', kind='adult_comments', keywords=['x'])
    with pytest.raises(ValueError):
        TaskInput(name='x', platform='ks', kind='crawler', keywords=['x'], max_items=100)
