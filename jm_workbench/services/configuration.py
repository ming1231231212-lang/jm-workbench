import json
import threading
import time
from pathlib import Path
from ..core.config import revision
from ..core.db import dumps, uid
from ..core.models import AccountInput, TaskInput, BindingInput
from ..core.platforms import PLATFORMS
from ..adapters.chrome import endpoint, open_browser
from ..adapters.errors import PlatformRisk
from ..adapters.kuaishou import Browser


class Configuration:
    def __init__(self, config, store, browser_factory=Browser):
        self.config, self.store = config, store
        self.browser_factory = browser_factory
        self.browser_lock = threading.RLock()
        self.code_revision = revision()

    def account(self, payload, ident=None):
        data = AccountInput.model_validate(payload).model_dump()
        ident = ident or uid()
        profile = Path(data['profile_dir'] or self.config.home / 'browser_profiles' / ident).resolve()
        if str(profile) == profile.anchor:
            raise ValueError('浏览器资料目录不能使用磁盘根目录')
        if any(a['id'] != ident and Path(a['profile_dir']).resolve() == profile for a in self.store.objects('account')):
            raise ValueError('此浏览器资料已绑定另一账号；每个账号使用独立资料目录')
        data.update(profile_dir=str(profile), connection='unverified', identity='', checked_at=0)
        if ident in {a['id'] for a in self.store.objects('account')}:
            old = self.store.get('account', ident)
            if data['platform'] == old['platform'] and data['profile_dir'] == old['profile_dir']:
                data.update({k: old.get(k) for k in ('connection', 'identity', 'checked_at')})
            elif any(b['account_id'] == ident for b in self.store.objects('binding')):
                raise ValueError('已绑定任务的账号不能更改平台或资料目录，请新增账号')
        result = self.store.put('account', data, ident)
        self.store.event('账号配置已保存：' + data['name'])
        return result

    def task(self, payload, ident=None):
        data = TaskInput.model_validate(payload).model_dump()
        if ident and any(b['task_id'] == ident for b in self.store.objects('binding')):
            if self.store.get('task', ident)['platform'] != data['platform']:
                raise ValueError('已绑定账号的任务不能更改平台，请新增任务')
        result = self.store.put('task', data, ident)
        self.store.event('任务配置已保存：' + data['name'])
        return result

    def binding(self, payload):
        data = BindingInput.model_validate(payload).model_dump()
        task = self.store.get('task', data['task_id'])
        account = self.store.get('account', data['account_id'])
        if task['platform'] != account['platform']:
            raise ValueError('任务与账号的平台不一致')
        if self.store.rows("SELECT 1 FROM runs WHERE task_id=? AND account_id=? AND state IN ('running','queued','waiting')",
                           (task['id'], account['id'])):
            raise ValueError('请先停止此绑定的活动任务')
        result = self.store.put('binding', data, task['id'] + '_' + account['id'])
        self.store.event('矩阵绑定已更新：' + task['name'] + ' / ' + account['name'])
        return result

    def check_account(self, ident):
        account = self.store.get('account', ident)
        if self.store.rows("SELECT 1 FROM runs WHERE account_id=? AND state='running'", (ident,)):
            raise ValueError('账号当前正在执行任务，请稍后检查')
        with self.browser_lock:
            endpoint(account['profile_dir'])
            if account['platform'] == 'ks':
                try:
                    with self.browser_factory(account) as browser:
                        who = browser.account()
                except PlatformRisk as ex:
                    self.store.lock('ks', str(ex))
                    raise
                identity = who.get('account_id', who.get('id', ''))
                if not identity:
                    raise ValueError('未取得平台登录身份')
                if account.get('identity') and account['identity'] != identity:
                    raise ValueError('浏览器当前身份已改变，请为新身份单独建立账号配置')
                account.update(identity=identity, connection='verified', checked_at=time.time())
            else:
                account.update(connection='connected', checked_at=time.time())
            result = self.store.put('account', account, ident)
        self.store.event('账号连接检查完成：' + account['name'])
        return result

    def open_account(self, ident):
        account = self.store.get('account', ident)
        if self.store.rows("SELECT 1 FROM runs WHERE account_id=? AND state='running'", (ident,)):
            raise ValueError('账号执行中，请先停止任务再打开主页')
        with self.browser_lock:
            return open_browser(self.config, account)

    def preflight(self, task_id=None):
        entries, errors = [], []
        for binding in self.store.objects('binding'):
            if not binding['enabled'] or (task_id and binding['task_id'] != task_id):
                continue
            task, account = self.store.get('task', binding['task_id']), self.store.get('account', binding['account_id'])
            if not task['enabled'] or not account['enabled']:
                continue
            reason = ''
            try:
                TaskInput.model_validate({k: v for k, v in task.items() if k not in ('id', 'version')})
                if task['platform'] != account['platform']:
                    raise ValueError('平台不匹配')
                if self.store.rows('SELECT 1 FROM risk WHERE platform=?', (task['platform'],)):
                    raise ValueError('平台限制尚未处理')
                if account['connection'] not in ('verified', 'connected'):
                    raise ValueError('请先检查账号连接')
                if task['kind'] != 'crawler' and not account.get('identity'):
                    raise ValueError('评论任务需要核验登录身份')
                if task['kind'] == 'crawler' and (task['platform'] != 'ks' or task['collect_comments']) and not self.config.crawler_ready():
                    raise ValueError('请先配置MediaCrawler运行目录及Python路径')
                endpoint(account['profile_dir'])
            except Exception as ex:
                reason = str(ex)
            row = {'task': task, 'account': account, 'binding': binding, 'reason': reason}
            (errors if reason else entries).append(row)
        if not entries and not errors:
            errors.append({'reason': '尚无启用的任务与账号绑定，请先配置任务和矩阵'})
        return entries, errors

    def launch(self, task_id=None):
        entries, errors = self.preflight(task_id)
        if errors:
            return {'ok': False, 'created': [], 'errors': [
                {'name': e.get('task', {}).get('name', '矩阵'), 'reason': e['reason']} for e in errors]}
        created, existing = [], []
        with self.store.connect(True) as db:
            for row in entries:
                task, account = row['task'], row['account']
                active = db.execute("SELECT id FROM runs WHERE task_id=? AND account_id=? AND state IN ('queued','running','waiting')",
                                    (task['id'], account['id'])).fetchone()
                if active:
                    existing.append(active['id'])
                    continue
                ident, now = uid(), time.time()
                snapshot = dict(row, revision=self.code_revision)
                db.execute('INSERT INTO runs(id,task_id,account_id,platform,state,snapshot,created,updated) '
                           'VALUES(?,?,?,?,?,?,?,?)', (ident, task['id'], account['id'], task['platform'], 'queued', dumps(snapshot), now, now))
                created.append(ident)
        self.store.event(f'一键执行：新增{len(created)}个任务，已有{len(existing)}个任务执行中')
        return {'ok': True, 'created': created, 'existing': existing, 'errors': []}
