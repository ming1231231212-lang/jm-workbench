"""Copied as jm_publish_guard.py into SAU by the reviewed installer.

Only JM requests enable the single-submit rule. The request owns its ContextVar;
asyncio inherits it and concurrent requests cannot change its state.
"""
import asyncio
import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar

VERSION = 1
_state = ContextVar('jm_publish_guard', default=None)
_lock = threading.Lock()


@contextmanager
def guarded(enabled):
    if not _lock.acquire(False):
        raise RuntimeError('SAU already has a video submission in progress')
    token = _state.set({'attempted': False, 'phases': set()} if enabled else None)
    try:
        if enabled and os.environ.get('SAU_DRY_RUN', '').lower() in ('1', 'true', 'yes'):
            raise RuntimeError('SAU dry-run cannot report a JM publication receipt')
        yield
    finally:
        _state.reset(token)
        _lock.release()


def before_submit(phase='publish'):
    state = _state.get()
    if state is not None:
        if phase in state['phases']:
            raise RuntimeError('JM refuses a repeated publication click')
        # Reserve before click: a timeout may mean the click already happened.
        state['phases'].add(phase)
        state['attempted'] = True


def stop_retry():
    state = _state.get()
    if state is not None and state['attempted']:
        raise RuntimeError('Publication outcome is uncertain; JM stopped retries')


def reject_verification():
    if _state.get() is not None:
        raise RuntimeError('Platform verification required; JM stopped this request')


def run(coroutine, debug=False, timeout=600):
    async def bounded():
        return await asyncio.wait_for(coroutine, timeout=timeout)
    return asyncio.run(bounded() if _state.get() is not None else coroutine, debug=debug)


def guard_status():
    # This function runs in the loaded backend, not a file-presence guess.
    return {'code': 200, 'data': {'version': VERSION, 'single_submit': True, 'timeout_seconds': 600}}
