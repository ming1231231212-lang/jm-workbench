import asyncio
from concurrent.futures import ThreadPoolExecutor
import pytest
from jm_workbench.publishing.sau_guard import guarded,before_submit,stop_retry,reject_verification,run


def test_publication_timeout_cannot_click_twice_even_if_caller_retries():
    clicks=[]
    with guarded(True):
        for _ in range(3):
            try:
                before_submit();clicks.append('click')
                raise TimeoutError('outcome unknown')
            except Exception:pass
        assert clicks==['click']
        with pytest.raises(RuntimeError,match='uncertain'):stop_retry()


def test_confirmation_is_allowed_once_and_keeps_no_retry_boundary():
    with guarded(True):
        before_submit();before_submit('confirm')
        with pytest.raises(RuntimeError):before_submit('confirm')
        with pytest.raises(RuntimeError):stop_retry()


def test_guard_resets_after_request_and_keeps_legacy_behavior():
    with guarded(True):before_submit()
    with guarded(True):before_submit()
    with guarded(False):
        before_submit();before_submit();stop_retry();reject_verification()


def test_parallel_requests_cannot_overwrite_guard():
    with guarded(True):
        def other():
            with guarded(True):pass
        with ThreadPoolExecutor(1) as pool:
            with pytest.raises(RuntimeError,match='progress'):pool.submit(other).result()
        before_submit()
        with pytest.raises(RuntimeError):before_submit()


def test_async_submits_inherit_guard_and_timeout_cancels_work():
    stopped=[]
    async def slow():
        before_submit()
        try:await asyncio.sleep(10)
        finally:stopped.append(True)
    with guarded(True):
        with pytest.raises(TimeoutError):run(slow(),timeout=.01)
        assert stopped==[True]
        with pytest.raises(RuntimeError):stop_retry()


def test_verification_and_dry_run_do_not_produce_success(monkeypatch):
    with guarded(True):
        with pytest.raises(RuntimeError,match='verification'):reject_verification()
    monkeypatch.setenv('SAU_DRY_RUN','1')
    with pytest.raises(RuntimeError,match='dry-run'):
        with guarded(True):pass
