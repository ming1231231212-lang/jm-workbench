"""Windows UI Automation channel bound to one task-owned everyday Chrome tab."""
import json
import hashlib
import os
import re
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
        self.readonly_replacement = False
        self.replaced = False
        self.state = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        self.expected=self.state.get('url','')
        self.shell = shutil.which('pwsh') or shutil.which('powershell')

    def raw(self, action, **kwargs):
        if os.name != 'nt' or not self.shell:
            raise NativeStopped('本机Chrome操作需要Windows可交互桌面')
        command = [self.shell, '-NoProfile', '-STA', '-File', str(ROOT / 'scripts/native_chrome.ps1')]
        if self.state.get('window'):
            if not self.state.get('process_id') or not self.state.get('process_started'):
                raise NativeStopped('日常Chrome窗口绑定不完整，未操作')
            command += ['-Window', str(self.state['window']),
                        '-ExpectedProcessId', str(self.state['process_id']),
                        '-ExpectedProcessStarted', str(self.state['process_started'])]
        try:
            p = self.runner(command,
                input=json.dumps({'action': action, **({'tab_key':self.state['key']} if self.state.get('key') and action not in ('new','tabs','select') else {}), **kwargs}, ensure_ascii=False),
                capture_output=True, encoding='utf-8', timeout=25,
                creationflags=subprocess.CREATE_NO_WINDOW, cwd=ROOT)
        except subprocess.TimeoutExpired as ex:
            raise TimeoutError('本机控件操作超时，未重试') from ex
        if p.returncode:
            raise NativeStopped((p.stderr or '本机Chrome操作未完成')[-1200:])
        result = json.loads(p.stdout)
        if all(result.get(k) for k in ('window', 'process_id', 'process_started')):
            self.state.update({k: result[k] for k in ('window', 'process_id', 'process_started')})
            self.save()
        return result

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.state, ensure_ascii=False), encoding='utf-8')
        temp.replace(self.path)

    @staticmethod
    def fingerprint(payload):
        return hashlib.sha256(json.dumps([payload['title'],payload['body']],ensure_ascii=False).encode()).hexdigest()

    def mark_draft(self,payload):
        self.state['draft']=self.fingerprint(payload);self.save()

    def clear_draft(self):
        self.state.pop('draft',None);self.save()

    def open_receipt(self,url,title):
        """Follow an observed result link after the single submit, not an editor."""
        from .registry import thread_url
        from .native import normalized
        old,new=urlsplit(self.expected),urlsplit(url)
        platform={'juejin.cn':'juejin','tieba.baidu.com':'tieba'}.get(old.hostname)
        expected_path={'juejin':'/published','tieba':'/f'}.get(platform)
        if not platform or old.path!=expected_path or new.hostname!=old.hostname or thread_url(platform,url)!=url:
            raise NativeStopped('回执导航不属于当前平台结果页，未离开原稿')
        s=self.call('snapshot')
        observed=[]
        for n in s.get('nodes',[]):
            if not n.get('visible') or n.get('type')!='Hyperlink' or normalized(title) not in normalized(n.get('name','')):continue
            try:observed.append(thread_url(platform,n.get('value','')))
            except ValueError:continue
        if url not in observed:
            raise NativeStopped('结果链接未在当前页面核对，未离开原稿')
        draft=self.state.pop('draft',None)
        try:return self.call('open',url=url)
        except Exception:
            if draft:self.state['draft']=draft;self.save()
            raise

    def resume_article(self,payload):
        if self.state.get('draft')!=self.fingerprint(payload):return None
        try:self.raw('select',key=self.state['key'])
        except NativeStopped:
            if self.replace_missing():return None
            raise
        self.expected=self.state['url']
        return self.call('follow_editor')

    def replace_missing(self):
        """A closed draft tab is recreated from the durable job, never resubmitted.

        Caller only reaches this before the reservation/submit boundary. Existing
        tabs, even repurposed ones, must not be overwritten or closed.
        """
        tabs=self.raw('tabs')['tabs']
        if any(t['key']==self.state.get('key') for t in tabs):return False
        self.release_tab();return True

    def release_tab(self):
        if self.replaced or not all(self.state.get(k) for k in ('window','process_id','process_started')):
            raise NativeStopped('本次无法安全恢复原窗口任务标签')
        self.state={k:self.state[k] for k in ('window','process_id','process_started')}
        self.expected='';self.replaced=True;self.save()

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
        self.state.update(key=candidates[0]['key'], url=s['url'])
        self.expected = s['url']; self.save()

    def call(self, action, **kwargs):
        if action in ('follow_editor', 'follow_published'):
            value = self.raw('url')['url']
            old, new = urlsplit(self.expected), urlsplit(value)
            valid = value == self.expected
            if action == 'follow_editor':
                valid = valid or (old.hostname == new.hostname == 'zhuanlan.zhihu.com' and old.path == '/write' and re.fullmatch(r'/p/[1-9][0-9]{3,23}/edit', new.path))
                valid = valid or (old.hostname == new.hostname == 'juejin.cn' and old.path == '/editor/drafts/new' and re.fullmatch(r'/editor/drafts/[1-9][0-9]{3,23}', new.path))
            elif action == 'follow_published':
                valid = valid or (old.hostname == new.hostname == 'zhuanlan.zhihu.com' and re.fullmatch(r'/p/[1-9][0-9]{3,23}/edit', old.path) and new.path == old.path.removesuffix('/edit'))
                valid = valid or (old.hostname == new.hostname == 'juejin.cn' and old.path.startswith('/editor/drafts/') and re.fullmatch(r'/post/[1-9][0-9]{15,23}', new.path))
                valid = valid or (old.hostname == new.hostname == 'juejin.cn' and old.path.startswith('/editor/drafts/') and new.path == '/published')
                valid = valid or (old.hostname == new.hostname == 'tieba.baidu.com' and old.path == '/f' and re.fullmatch(r'/p/[1-9][0-9]{3,23}', new.path))
            if not valid:
                raise NativeStopped('页面没有按预期进入本次编辑或结果页，未接管其他页面')
            self.expected = value; self.state['url'] = value; self.save()
            return self.raw('snapshot', expected_url=value)
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
        if not self.state.get('key'):
            self.raw('new')
            tabs = [t for t in self.raw('tabs')['tabs'] if t.get('selected')]
            if len(tabs) != 1: raise NativeStopped('新建任务标签无法唯一核对，未导航')
            self.state.update(key=tabs[0]['key'], url='', new=True); self.save()
            self.state.update(key=tabs[0]['key'], url=self.raw('url')['url'])
            self.state.pop('new', None)
            self.save()
        try:self.raw('select', key=self.state['key'])
        except NativeStopped:
            if self.replace_missing():return self.call('open',**kwargs)
            raise
        actual = self.raw('url')['url']
        if actual != self.state['url']:
            self.expected=self.state['url']
            try:self.call('follow_editor')
            except NativeStopped:
                if not self.readonly_replacement:raise
                self.release_tab();return self.call('open',**kwargs)
            actual=self.state['url']
        if self.state.get('draft') and url!=actual:
            raise NativeStopped('本任务有未提交文章，已保留原稿，未导航')
        if actual != self.state['url']:
            raise NativeStopped('本任务标签已被用于其他页面，未覆盖')
        self.raw('navigate', expected_url=actual, url=url)
        self.redirects = redirects
        self.state['url'] = url; self.expected = url; self.save()
        return {'url': url}
