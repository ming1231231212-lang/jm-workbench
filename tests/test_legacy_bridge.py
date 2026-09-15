import importlib.util
from pathlib import Path
from scripts.install_legacy_bridge import install

def test_legacy_redirect_has_backup_and_never_falls_back(tmp_path):
    project=tmp_path/'jm'
    (project/'scripts').mkdir(parents=True)
    (project/'scripts'/'legacy_bridge.py').write_text('def main(): return 0\n')
    runtime=tmp_path/'old'
    (runtime/'adult_outreach').mkdir(parents=True)
    for name in ['_adult_launch.py','_adult_guard.py','_adult_wrap.py']:
        (runtime/name).write_text('print("old")\n')
    (runtime/'adult_outreach'/'legacy.py').write_text('def publisher_args(args):\n    return None\ndef legacy_send_allowed(video_id):\n    return True\n')
    install(runtime,project)
    assert 'from _jm_bridge import main' in (runtime/'_adult_launch.py').read_text()
    assert list((project/'outputs').glob('legacy-backup-*/legacy.py'))
    namespace={}
    exec((runtime/'adult_outreach'/'legacy.py').read_text(),namespace)
    assert namespace['legacy_send_allowed']('anyvideo') is False
