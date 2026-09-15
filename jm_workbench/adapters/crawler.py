"""Run the separately installed crawler in an isolated, bounded child process."""
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
from .chrome import endpoint
from .errors import Cancelled, LocalBrowserError, PlatformRisk


def parameters(config, run, keyword):
    task, account = run['snapshot']['task'], run['snapshot']['account']
    work = config.home / 'runs' / run['id']
    work.mkdir(parents=True, exist_ok=True)
    return {'platform': task['platform'], 'keyword': keyword, 'max_items': task['max_items'],
            'collect_comments': task['collect_comments'], 'comments_per_item': task['comments_per_item'],
            'root': config.values['crawler_root'], 'output': str(work),
            'endpoint': endpoint(account['profile_dir'])}


class Crawler:
    def __init__(self, config):
        self.config = config

    def run(self, run, keyword, cancelled=lambda: False):
        params = parameters(self.config, run, keyword)
        work = Path(params['output'])
        path = work / 'parameters.json'
        path.write_text(json.dumps(params, ensure_ascii=False), encoding='utf-8')
        result_path = work / 'result.json'
        result_path.unlink(missing_ok=True)
        # Child prints are discarded: upstream messages can contain account cookies.
        proc = subprocess.Popen([self.config.values['crawler_python'], str(Path(__file__).with_name('crawler_child.py')), str(path)],
                                cwd=params['root'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + 600
        while proc.poll() is None:
            if cancelled() or time.monotonic() > deadline:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                if cancelled():
                    raise Cancelled('任务已停止，已保留本次读取结果')
                raise LocalBrowserError('爬虫执行超过10分钟，已停止；请检查登录和平台页面')
            time.sleep(.25)
        if not result_path.is_file():
            raise LocalBrowserError('爬虫运行失败，请检查运行依赖；未取得完成记录')
        result = json.loads(result_path.read_text(encoding='utf-8'))
        if result['state'] == 'risk':
            raise PlatformRisk(result['message'])
        if result['state'] != 'completed':
            raise LocalBrowserError(result['message'])
        return result['items']
