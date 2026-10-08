import json
import socket
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jm_workbench import portable
from jm_workbench.web.app import create_app
from jm_workbench.publishing.service import probe_video_embedded


def test_instance_identity_does_not_leak_home_and_distinguishes_installations(tmp_path):
    with TestClient(create_app(tmp_path / 'a', worker=False), base_url='http://127.0.0.1:8776') as client:
        response = client.get('/api/health').json()
    assert response['instance_id'] == portable.instance_id(tmp_path / 'a')
    assert response['instance_id'] != portable.instance_id(tmp_path / 'b')
    assert str(tmp_path) not in json.dumps(response)


def test_config_upgrade_keeps_user_data_and_custom_choices(tmp_path, monkeypatch):
    monkeypatch.setattr(portable, 'browser_path', lambda bundle: bundle / 'browser/chrome.exe')
    home = tmp_path / '中文 用户数据'
    first = portable.configure(home, tmp_path / 'old')
    assert not (home / 'jm.db').exists()
    original = home / 'sentinel.txt'
    original.write_text('preserved')
    values = dict(first, crawler_root='My licensed crawler', chrome_path='My custom Chrome')
    portable.atomic_json(home / 'config.local.json', values)
    second = portable.configure(home, tmp_path / 'new')
    assert second['chrome_path'] == 'My custom Chrome'
    assert second['crawler_root'] == 'My licensed crawler'
    assert second['sau_url'] == first['sau_url']
    assert original.read_text() == 'preserved'


def test_relocation_updates_only_managed_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(portable, 'browser_path', lambda bundle: bundle / 'chrome.exe')
    portable.configure(tmp_path / 'data', tmp_path / 'old')
    changed = portable.configure(tmp_path / 'data', tmp_path / 'new')
    assert changed['chrome_path'] == str(tmp_path / 'new/chrome.exe')


def test_missing_installed_chrome_falls_back_to_bundle(tmp_path, monkeypatch):
    for name in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
        monkeypatch.setenv(name, str(tmp_path/'empty'))
    monkeypatch.delenv('JM_BUNDLED_BROWSER', raising=False)
    executable = tmp_path/'browser/chromium-1228/chrome-win64/chrome.exe'
    executable.parent.mkdir(parents=True)
    executable.touch()
    assert portable.browser_path(tmp_path) == executable


def test_port_collision_does_not_adopt_another_service():
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        assert portable.free_port(port) != port
        assert occupied.getsockname()[1] == port


def test_exclusive_lock_and_clean_release(tmp_path):
    first, second = portable.InstanceLock(tmp_path), portable.InstanceLock(tmp_path)
    try:
        assert first.acquire()
        assert not second.acquire()
        first.close()
        assert second.acquire()
    finally:
        first.close()
        second.close()


def test_bad_video_never_accepted_by_metadata_only(monkeypatch):
    class BadCapture:
        def isOpened(self): return True
        def get(self, _): return 24
        def read(self): return False, None
        def release(self): pass
    monkeypatch.setitem(sys.modules, 'cv2', types.SimpleNamespace(VideoCapture=lambda *a, **k: BadCapture(),
        CAP_FFMPEG=1, CAP_PROP_OPEN_TIMEOUT_MSEC=2, CAP_PROP_READ_TIMEOUT_MSEC=3, CAP_PROP_FPS=4, CAP_PROP_FRAME_COUNT=5))
    with pytest.raises(ValueError, match='损坏'):
        probe_video_embedded('metadata-without-frame')


def test_clean_first_start_no_account_plan_or_posts(tmp_path):
    with TestClient(create_app(tmp_path, worker=False), base_url='http://127.0.0.1:8776') as client:
        state = client.get('/api/state').json()
        community = client.get('/api/community/state').json()
    assert state['accounts'] == state['tasks'] == state['runs'] == []
    assert community['accounts'] == community['posts'] == []
