"""Windows UI Automation channel bound to one task-owned everyday Chrome tab."""
import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from ..core.config import ROOT
from .native import NativeStopped


class NativeChromeChannel:
    def __init__(self, state_path, *, runner=subprocess.run):
        self.path = Path(state_path)
        self.runner = runner
        self.expected = ''
        self.redirects = []
        self.state = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        self.shell = shutil.which('pwsh') or shutil.which('powershell')

    def raw(self, action, **kwargs):
        if os.name != 'nt' or not self.shell:
            raise NativeStopped('本机Chrome操作需要Windows可交互桌面')
        try:
            p = self.runner([self.shell, '-NoProfile', '-STA', '-File', str(ROOT / 'scripts/native_chrome.ps1')],
                input=json.dumps({'action': action, **kwargs}, ensure_ascii=False),
                capture_output=True, encoding='utf-8', timeout=25,
                creationflags=subprocess.CREATE_NO_WINDOW, cwd=ROOT)
        except subprocess.TimeoutExpired as ex:
            raise TimeoutError('本机控件操作超时，未重试') from ex
        if p.returncode:
            raise NativeStopped((p.stderr or '本机Chrome操作未完成')[-1200:])
        return json.loads(p.stdout)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.state, ensure_ascii=False), encoding='utf-8')
        temp.replace(self.path)

    def adopt(self, title_prefix, expected_url):
        """Only for the already-created task tab; requires an explicit exact URL."""
        tabs = self.raw('tabs')['tabs']
        candidates = [t for t in tabs if t['name'].startswith(title_prefix)]
        if len(candidates) != 1:
            raise NativeStopped('本任务标签不存在或不唯一，未接管其他页面')
        self.raw('select', key=candidates[0]['key'])
        s = self.raw('snapshot', expected_url=expected_url)
        if not s.get('text'):
            raise NativeStopped('本任务标签的实际网址不一致，未接管')
        self.state = {'key': candidates[0]['key'], 'url': s['url']}
        self.expected = s['url']; self.save()

    def call(self, action, **kwargs):
        if action != 'open':
            if action == 'snapshot':
                kwargs['expected_url'] = self.expected
                value = self.raw(action, **kwargs)
                if not value.get('text') and value.get('url') in self.redirects:
                    self.expected = value['url']; self.state['url'] = self.expected; self.save()
                    value = self.raw(action, expected_url=self.expected)
                return value
            return self.raw(action, **kwargs)
        url = kwargs['url']
        redirects = kwargs.get('allowed_redirects', [])
        for value in [url, *redirects] if redirects else []:
            u = urlsplit(value)
            if u.scheme != 'https' or u.hostname != 'www.zhihu.com' or not u.path.startswith('/people/') or u.query or u.fragment or u.username or u.port:
                raise NativeStopped('主页跳转不在已绑定的账号范围')
        if not self.state:
            raise NativeStopped('本次发布没有已核对的任务专用标签，未改动其他页面')
        self.raw('select', key=self.state['key'])
        s = self.raw('snapshot', expected_url=self.state['url'])
        if not s.get('text'):
            raise NativeStopped('本任务标签已被用于其他页面，未覆盖')
        self.raw('navigate', expected_url=s['url'], url=url)
        self.redirects = redirects
        self.state['url'] = url; self.expected = url; self.save()
        return {'url': url}
