"""Local state-file contention must never become a permanent platform pause."""
import ctypes
import json
import os
from contextlib import contextmanager, nullcontext
from pathlib import Path

import pytest

from test_community_replies import ctx
from test_community_daily import setup_plan
from jm_workbench.community.adapters import RetryablePreflight
from jm_workbench.community.models import DailyPlan
from jm_workbench.community.native_channel import NativeChromeChannel
from jm_workbench.community.native_runtime import NativeRuntime


@contextmanager
def windows_reader(path):
    """A real Windows reader without FILE_SHARE_DELETE blocks atomic replace."""
    from ctypes import wintypes
    dll = ctypes.WinDLL('kernel32', use_last_error=True)
    dll.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    dll.CreateFileW.restype = wintypes.HANDLE
    dll.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = dll.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
    try:
        yield
    finally:
        dll.CloseHandle(handle)


@pytest.mark.skipif(os.name != 'nt', reason='Windows file sharing semantics')
def test_unchanged_state_needs_no_write_even_when_windows_reader_holds_file(tmp_path):
    ui = NativeChromeChannel(tmp_path/'tab.json')
    ui.state = {'url': 'https://fixture.example/', 'draft': 'keep-original'}
    ui.save()
    before = ui.path.stat().st_mtime_ns
    with windows_reader(ui.path):
        ui.save()
    assert ui.path.stat().st_mtime_ns == before
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.skipif(os.name != 'nt', reason='Windows file sharing semantics')
def test_atomic_save_retries_real_windows_sharing_failure_then_succeeds(tmp_path, monkeypatch):
    ui = NativeChromeChannel(tmp_path/'tab.json')
    ui.state = {'url': 'https://fixture.example/', 'draft': 'old'}
    ui.save()
    ui.state['draft'] = 'new'
    original = Path.replace
    failures = []
    def replace(source, destination):
        if not failures:
            with windows_reader(destination):
                try:
                    original(source, destination)
                except PermissionError as error:
                    failures.append(error.winerror)
                    raise
        return original(source, destination)
    monkeypatch.setattr(Path, 'replace', replace)
    monkeypatch.setattr('jm_workbench.community.native_channel.time.sleep', lambda _: None)
    ui.save()
    assert len(failures) == 1 and failures[0] in (5, 32)
    assert json.loads(ui.path.read_text(encoding='utf-8')) == ui.state
    assert not list(tmp_path.glob('*.tmp'))


def test_save_preserves_old_state_and_uses_own_unique_temporary_file(tmp_path, monkeypatch):
    ui = NativeChromeChannel(tmp_path/'tab.json')
    ui.state = {'draft': 'preserved'}
    ui.save()
    legacy = ui.path.with_suffix('.tmp')
    legacy.write_text('older failure evidence', encoding='utf-8')
    calls = []
    def denied(source, destination):
        calls.append(source)
        raise PermissionError(13, 'fixture locked', str(destination))
    monkeypatch.setattr(Path, 'replace', denied)
    monkeypatch.setattr('jm_workbench.community.native_channel.time.sleep', lambda _: None)
    ui.state['draft'] = 'next'
    with pytest.raises(PermissionError):
        ui.save()
    assert len(calls) == 4
    assert all(p != legacy for p in calls)
    assert legacy.read_text(encoding='utf-8') == 'older failure evidence'
    assert json.loads(ui.path.read_text(encoding='utf-8')) == {'draft': 'preserved'}
    assert list(tmp_path.glob('*.tmp')) == [legacy]


@pytest.mark.parametrize('entered', [False, True])
def test_permission_error_respects_submit_boundary_and_retains_safe_diagnostics(ctx, monkeypatch, entered):
    s, _, a, _ = ctx
    runtime = NativeRuntime(s.cfg.config)
    monkeypatch.setattr('jm_workbench.community.native_runtime.desktop_lock', lambda _: nullcontext())
    class Publisher:
        before_submit = staticmethod(lambda: None)
        def publish(self, *_):
            if entered:
                self.before_submit()
            raise PermissionError(13, 'must-not-store-secret', 'private-file.json')
    monkeypatch.setattr(runtime, 'publisher', lambda *_: Publisher())
    with pytest.raises(PermissionError if entered else RetryablePreflight) as raised:
        runtime.publish({**s.account(a), 'native_binding': {}}, {}, '')
    if not entered:
        diagnostic = raised.value.local_error
        assert diagnostic['type'] == 'PermissionError' and diagnostic['errno'] == 13
        assert diagnostic['file'] == 'private-file.json'
        assert diagnostic['frames'][-1]['function'] == 'publish'
        assert 'must-not-store-secret' not in json.dumps(diagnostic)


@pytest.mark.parametrize('where', ['lock', 'channel'])
def test_permission_failure_before_publisher_creation_is_retryable(ctx, monkeypatch, where):
    s, _, a, _ = ctx
    runtime = NativeRuntime(s.cfg.config)
    def denied(*_):
        raise PermissionError(13, 'fixture access denied')
    monkeypatch.setattr('jm_workbench.community.native_runtime.desktop_lock', denied if where == 'lock' else lambda _: nullcontext())
    if where == 'channel':
        monkeypatch.setattr(runtime, 'publisher', denied)
    with pytest.raises(RetryablePreflight):
        runtime.publish({**s.account(a), 'native_binding': {}}, {}, '')


def test_queue_recovers_same_post_after_local_permission_error_and_restart(ctx, monkeypatch):
    s, fake, a, now = ctx
    plan = setup_plan(ctx)
    s.daily.control(plan, 'pause')
    data = s.daily.get(plan)['payload']
    data.update(replies_per_day=0, hour=1, minute=0)
    s.daily.save(DailyPlan(**data), plan)
    s.daily.control(plan, 'enable')
    s.daily.prepare(plan)
    runtime = NativeRuntime(s.cfg.config)
    monkeypatch.setattr('jm_workbench.community.native_runtime.desktop_lock', lambda _: nullcontext())
    class Publisher:
        before_submit = staticmethod(lambda: None)
        def publish(self, *_):
            raise PermissionError(13, 'fixture denied', 'task.json')
    monkeypatch.setattr(runtime, 'publisher', lambda *_: Publisher())
    real = fake.publish
    fake.publish = lambda account, secret, payload, target: runtime.publish({**account, 'native_binding': {}}, payload, target)
    s.tick()
    first = s.store.rows('SELECT * FROM community_jobs')[0]
    assert first['state'] == 'queued' and first['started'] == 0
    assert s.daily.get(plan)['state'] == 'enabled' and not s.state()['risk']
    history = json.loads(first['receipt'])['preflight_history']
    assert history[-1]['local_error']['errno'] == 13
    s.recover()
    fake.publish = real
    now[0] = first['due']
    s.tick()
    jobs = s.store.rows('SELECT * FROM community_jobs')
    assert len(jobs) == 1 and jobs[0]['id'] == first['id'] and jobs[0]['state'] == 'submitted'
    assert json.loads(jobs[0]['receipt'])['preflight_history'] == history
    assert len(fake.sent) == 1 and s.daily.get(plan)['state'] == 'enabled'


def test_permission_error_after_durable_submit_never_requeues(ctx, monkeypatch):
    from jm_workbench.community.native_runtime import reserve_submit
    s, fake, a, now = ctx
    plan = setup_plan(ctx)
    s.daily.control(plan, 'pause')
    data = s.daily.get(plan)['payload']; data['replies_per_day'] = 0
    s.daily.save(DailyPlan(**data), plan); s.daily.control(plan, 'enable'); s.daily.prepare(plan)
    runtime = NativeRuntime(s.cfg.config)
    monkeypatch.setattr('jm_workbench.community.native_runtime.desktop_lock', lambda _: nullcontext())
    class Publisher:
        def __init__(self, account, payload, target):
            self.before_submit = lambda: reserve_submit(s.cfg.config, account, payload, target, lambda: now[0])
        def publish(self, *_):
            self.before_submit()
            raise PermissionError(13, 'fixture result-state save blocked')
    monkeypatch.setattr(runtime, 'publisher', lambda *args: Publisher(*args))
    fake.publish = lambda account, secret, payload, target: runtime.publish({**account, 'native_binding': {}}, payload, target)
    s.tick()
    before = s.store.rows('SELECT * FROM community_jobs')
    assert len(before) == 1 and before[0]['state'] == 'unknown'
    assert json.loads(before[0]['receipt'])['phase'] == 'native_submit_reserved'
    assert s.state()['risk']
    s.recover(); now[0] += 86400; s.tick()
    assert s.store.rows('SELECT * FROM community_jobs') == before
