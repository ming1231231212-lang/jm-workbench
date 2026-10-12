"""Bound external calls with owned subprocesses, never kill the user's Chrome.

Secrets travel through stdin only. No detached timeout threads may continue a
write after the queue has declared failure. Injected test adapters stay inline.
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from ..core.config import ROOT
from .adapters import CommunityAdapter, NotSubmitted, PreflightStopped, RetryablePreflight, IdentityChanged

ERRORS = {c.__name__: c for c in (NotSubmitted, PreflightStopped, RetryablePreflight, IdentityChanged)}
LABELS = {'ensure_connection':'连接浏览器', 'check':'检查账号', 'discover':'查找合适原帖', 'publish':'提交内容并等待回执'}
LIMITS = {'ensure_connection':30, 'check':60, 'discover':120, 'publish':180}


class ProcessBoundary:
    def __init__(self, home=None, command=None):
        self.command = command or [sys.executable, '-m', 'jm_workbench.community.browser_task', str(home)]
        self.lock = threading.Lock()
        self.processes = {}
        self.closed = False

    @staticmethod
    def terminate(child):
        if child.poll() is not None: return
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=5, check=False)
        else:
            try: os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        if child.poll() is None: child.kill()
        child.wait(timeout=5)

    def call(self, action, args, timeout):
        settings = {'creationflags':subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session':True}
        with self.lock:
            if self.closed: raise RuntimeError('执行器已停止')
            child = subprocess.Popen(self.command, cwd=ROOT, env={**os.environ, 'PYTHONPATH':str(ROOT)},
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **settings)
            self.processes[child.pid] = (child, {'action':action, 'label':LABELS[action],
                'platform':args[0].get('platform',''), 'started_at':time.time(), 'deadline_at':time.time()+timeout})
        try:
            try:
                output, _ = child.communicate(json.dumps({'action':action,'args':args}, ensure_ascii=False).encode(), timeout=timeout)
            except subprocess.TimeoutExpired:
                self.terminate(child)
                child.communicate(timeout=2)
                raise TimeoutError(LABELS[action]+'超时，已停止本次操作') from None
            if child.returncode != 0 or len(output)>2_000_000:
                raise RuntimeError('本地浏览器操作未正常结束')
            try:
                result=json.loads(output)
                if result['ok'] is True: return result['value']
                error=ERRORS.get(result.get('type'), RuntimeError)
                # Only deliberate, classified adapter errors may reach the UI.
                raise error(result.get('message','操作未完成') if error is not RuntimeError else '操作结果未明确返回')
            except (ValueError, KeyError, TypeError) as ex:
                if isinstance(ex, NotSubmitted): raise
                raise RuntimeError('本地执行结果无效') from None
        finally:
            if child.poll() is None: self.terminate(child)
            with self.lock: self.processes.pop(child.pid, None)

    def active(self):
        with self.lock: return [dict(value[1]) for value in self.processes.values()]

    def close(self):
        with self.lock:
            self.closed=True
            children=[value[0] for value in self.processes.values()]
        for child in children: self.terminate(child)


class BoundedCommunityAdapter:
    def __init__(self, config, boundary=None):
        self.local = CommunityAdapter(config)
        self.boundary = boundary or ProcessBoundary(config.home)
        self.operation_lock=threading.Lock()

    def _call(self, action, *args):
        if not self.operation_lock.acquire(blocking=False):
            raise RetryablePreflight('浏览器正在处理其他操作，当前动作未提交；请稍后检查')
        try: return self.boundary.call(action, args, LIMITS[action])
        except TimeoutError:
            if action == 'publish': raise
            raise RetryablePreflight(LABELS[action]+'超时，未提交；稍后会重新检查连接') from None
        finally:self.operation_lock.release()

    def ensure_connection(self, account): return self._call('ensure_connection', account)
    def check(self, account, secret): return self._call('check', account, secret)
    def discover(self, account, boards): return self._call('discover', account, boards)
    def publish(self, account, secret, payload, target): return self._call('publish', account, secret, payload, target)
    def open(self, account, url): return self.local.open(account, url)
    def active(self): return self.boundary.active()
    def close(self): self.boundary.close()
