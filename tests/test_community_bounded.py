"""Exercise real process boundaries; a timeout must not leave a writer alive."""
import json
import sys
import time
import pytest
from jm_workbench.community.bounded import ProcessBoundary, BoundedCommunityAdapter
from jm_workbench.community.adapters import RetryablePreflight, IdentityChanged
from jm_workbench.core.config import Config


def test_success_round_trip_and_credentials_are_not_command_arguments(tmp_path):
    boundary = ProcessBoundary(command=[sys.executable, '-c',
        'import json,sys; v=json.load(sys.stdin); print(json.dumps({"ok":True,"value":v["args"][1]}))'])
    assert boundary.call('check', [{}, 'private-key'], .5) == 'private-key'
    assert 'private-key' not in ' '.join(boundary.command)
    assert boundary.active() == []


def test_hard_timeout_terminates_writer_and_leaves_no_late_write(tmp_path):
    marker = tmp_path/'late-write'
    program = 'import json,sys,time,pathlib; json.load(sys.stdin); time.sleep(.6); pathlib.Path(sys.argv[1]).write_text("late")'
    boundary = ProcessBoundary(command=[sys.executable, '-c', program, str(marker)])
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        boundary.call('publish', [{'platform':'tieba'}], .1)
    assert time.monotonic()-started < 3
    time.sleep(.7)
    assert not marker.exists()
    assert boundary.active() == []


def test_exception_types_survive_boundary():
    boundary = ProcessBoundary(command=[sys.executable, '-c',
        'import json; print(json.dumps({"ok":False,"type":"IdentityChanged","message":"identity changed"}))'])
    with pytest.raises(IdentityChanged, match='identity changed'):
        boundary.call('check', [{}], 1)


def test_read_timeout_is_retryable_but_publish_timeout_is_uncertain(tmp_path):
    class Hanging:
        def call(self, *a): raise TimeoutError('timeout')
        def active(self): return []
        def close(self): pass
    adapter = BoundedCommunityAdapter(Config(tmp_path), boundary=Hanging())
    with pytest.raises(RetryablePreflight, match='未提交'):
        adapter.check({'platform':'tieba'}, '')
    with pytest.raises(TimeoutError):
        adapter.publish({'platform':'tieba'}, '', {}, 'ai')


def test_untrusted_worker_output_does_not_become_success():
    boundary = ProcessBoundary(command=[sys.executable, '-c', 'print("not json")'])
    with pytest.raises(RuntimeError): boundary.call('publish', [{}], 1)


def test_close_terminates_only_boundary_owned_processes():
    import threading
    boundary = ProcessBoundary(command=[sys.executable, '-c', 'import time; time.sleep(30)'])
    errors = []
    def work():
        try: boundary.call('check', [{'platform':'tieba'}], 30)
        except Exception as ex: errors.append(ex)
    thread = threading.Thread(target=work); thread.start()
    deadline = time.monotonic()+2
    while not boundary.active() and time.monotonic()<deadline: time.sleep(.01)
    boundary.close(); thread.join(3)
    assert not thread.is_alive()
    assert errors and boundary.active() == []


def test_real_worker_protocol_classifies_unsupported_auto_check_without_browser(tmp_path):
    boundary=ProcessBoundary(tmp_path)
    from jm_workbench.community.adapters import NotSubmitted
    with pytest.raises(NotSubmitted,match='网页发布'):
        boundary.call('check',[{'platform':'wechat_mp'},''],5)
    assert not boundary.active()


def test_timeout_kills_owned_driver_descendants(tmp_path):
    marker=tmp_path/'child-write'
    driver='import time,pathlib,sys;time.sleep(1);pathlib.Path(sys.argv[1]).write_text("late")'
    parent='import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2]]);time.sleep(30)'
    boundary=ProcessBoundary(command=[sys.executable,'-c',parent,driver,str(marker)])
    with pytest.raises(TimeoutError):boundary.call('publish',[{}],.2)
    time.sleep(1.1)
    assert not marker.exists()


def test_browser_busy_is_a_proven_unsent_operation(tmp_path):
    adapter=BoundedCommunityAdapter(Config(tmp_path))
    adapter.operation_lock.acquire()
    try:
        with pytest.raises(RetryablePreflight,match='未提交'):
            adapter.publish({'platform':'tieba'},'',{},'人工智能')
        assert not adapter.active()
    finally:adapter.operation_lock.release()
