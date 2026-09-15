import pytest
from jm_workbench.core.instance import InstanceLock

def test_single_worker_owner(tmp_path):
    first=InstanceLock(tmp_path/'lock')
    try:
        with pytest.raises(RuntimeError, match='第二个'):
            InstanceLock(tmp_path/'lock')
    finally:
        first.close()
    InstanceLock(tmp_path/'lock').close()
