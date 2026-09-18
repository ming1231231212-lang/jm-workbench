"""Local process supervision; never launches tasks or changes business records."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

from jm_workbench.core.config import ROOT, revision
from jm_workbench.core.instance import InstanceLock


def health(port):
    # Local availability must not depend on Windows/system proxy settings.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f'http://127.0.0.1:{port}/api/health', timeout=3) as response:
            result = json.load(response)
        return result if isinstance(result, dict) else None
    except (OSError, ValueError):
        return None


def port_open(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            return True
    except OSError:
        return False


def atomic_json(path, value):
    temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


class Watchdog:
    def __init__(self, config_path, clock=time.time, sleep=time.sleep):
        self.config_path = Path(config_path).resolve()
        self.home = self.config_path.parent
        self.state_path = self.home/'service-watchdog-state.json'
        self.clock, self.sleep = clock, sleep
        self.state = {}
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding='utf-8'))
        self.state['watchdog_pid'] = os.getpid()
        self.log = logging.getLogger('jm-service-watchdog')

    def config(self):
        config = json.loads(self.config_path.read_text(encoding='utf-8-sig'))
        if (config.get('version') != 1 or type(config.get('port')) is not int
                or not 1024 <= config['port'] <= 65535 or config.get('poll_seconds') != 30
                or not isinstance(config.get('app_revision'), str)):
            raise ValueError('守护配置无效，请重新配置自动恢复')
        return config

    def record(self, status, message, **extra):
        if self.state.get('status') != status or self.state.get('message') != message:
            self.log.info('%s: %s', status, message)
        self.state.update(status=status, message=message, checked_at=self.clock(), **extra)
        atomic_json(self.state_path, self.state)
        return dict(self.state)

    def worker_busy(self):
        try:
            lock = InstanceLock(self.home/'worker.lock')
        except RuntimeError:
            return True
        lock.close()
        return False

    def spawn(self, port):
        python = ROOT/'.venv'/'Scripts'/'python.exe'
        if not python.is_file():
            raise ValueError('工作台Python不存在')
        log_path = self.home/'service-watchdog-server.log'
        if log_path.exists() and log_path.stat().st_size > 2_000_000:
            log_path.replace(log_path.with_suffix('.previous.log'))
        kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
        with log_path.open('ab') as output:
            return subprocess.Popen([str(python), '-m', 'jm_workbench', '--home', str(self.home), '--port', str(port)],
                                    cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                    close_fds=True, **kwargs)

    @staticmethod
    def expected(data, expected_revision):
        return (data is not None and data.get('app_id') == 'jm-workbench'
                and data.get('worker') is True and data.get('revision') == expected_revision)

    def step(self):
        now, config = self.clock(), self.config()
        if (self.home/'service-watchdog.disabled').exists():
            return self.record('disabled', '自动恢复已暂停；不改变工作台任务状态')
        if revision() != config['app_revision']:
            return self.record('revision_changed', '业务代码已变化，待重新确认守护版本；不启动旧快照任务')
        if not (self.home/'jm.db').is_file():
            return self.record('missing_database', '原数据目录缺少数据库，未创建空工作台')
        current = health(config['port'])
        if self.expected(current, config['app_revision']):
            stable_since = self.state.get('stable_since') or now
            if now-stable_since >= 120:
                self.state.update(consecutive_restarts=0, next_restart_at=0)
            return self.record('healthy', '后台服务正常', stable_since=stable_since, last_healthy_at=now)
        self.state['stable_since'] = 0
        if current is not None or port_open(config['port']):
            return self.record('occupied_or_unhealthy', '端口仍被占用或返回非预期服务，未终止进程或启动第二份服务')
        if self.worker_busy():
            return self.record('worker_busy', '原执行器仍持有锁，等待启动完成或释放，不重复启动')
        if now < self.state.get('next_restart_at', 0):
            return self.record('backoff', '等待恢复间隔，避免连续启动失败')
        count = self.state.get('consecutive_restarts', 0)+1
        self.state.update(consecutive_restarts=count, restart_count=self.state.get('restart_count', 0)+1,
                          last_restart_at=now, next_restart_at=now+min(300, 30*2**min(count-1, 4)))
        self.record('starting', '检测到服务停止，正在恢复原工作台')
        try:
            child = self.spawn(config['port'])
            self.state['server_pid'] = child.pid
            for _ in range(20):
                if self.expected(health(config['port']), config['app_revision']):
                    return self.record('recovered', '后台服务已恢复；业务队列按原状态及保护规则处理',
                                       last_recovered_at=self.clock(), stable_since=self.clock())
                if child.poll() is not None:
                    break
                self.sleep(1)
        except (OSError, ValueError) as ex:
            return self.record('start_failed', '服务启动失败：'+str(ex)[:200])
        return self.record('start_unconfirmed', '服务尚未返回有效健康结果；下次检查仍先核验端口与执行器锁')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(ROOT/'var'/'service-watchdog.json'))
    parser.add_argument('--configure', action='store_true')
    parser.add_argument('--port', type=int, default=8776)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    path = Path(args.config).resolve()
    if args.configure:
        if not (path.parent/'jm.db').is_file():
            raise ValueError('必须先配置已有工作台数据库')
        if not Watchdog.expected(health(args.port), revision()):
            raise ValueError('先启动并核验当前业务版本，再启用自动恢复')
        atomic_json(path, {'version':1,'port':args.port,'poll_seconds':30,'app_revision':revision()})
        print('守护版本与当前服务已核验')
        return
    try:
        lock = InstanceLock(path.parent/'service-watchdog.lock')
    except RuntimeError:
        return  # scheduled repetition never creates another checker
    logger = logging.getLogger('jm-service-watchdog')
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(path.parent/'service-watchdog.log', maxBytes=1_000_000, backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    logger.addHandler(handler)
    try:
        watcher = Watchdog(path)
        while True:
            try:
                watcher.step()
            except Exception as ex:
                watcher.record('check_error', '守护检查异常：'+type(ex).__name__+'；未操作业务队列')
            if args.once:
                break
            time.sleep(30)
    finally:
        handler.close()
        lock.close()


if __name__ == '__main__':
    main()
