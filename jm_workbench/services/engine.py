import json
import threading
import time
from ..core.config import revision
from ..core.db import dumps
from ..core.instance import InstanceLock
from ..adapters.crawler import Crawler
from ..adapters.errors import Cancelled, LocalBrowserError, PlatformRisk
from ..policies.rules import assess, detail_ready
from .guard import read_slot, comment_due, reserve, finish, contact_reason, recover


class Engine:
    def __init__(self, configuration, crawler=None, clock=time.time):
        self.cfg = configuration
        self.store = configuration.store
        self.crawler = crawler or Crawler(configuration.config)
        self.clock = clock
        self.shutdown = threading.Event()
        self.step_lock = threading.Lock()
        self.thread = None
        self.instance_lock = None

    def start(self):
        self.instance_lock = InstanceLock(self.cfg.config.home/'worker.lock')
        recover(self.store)
        self.thread = threading.Thread(target=self.loop, name='jm-worker', daemon=True)
        self.thread.start()

    def close(self):
        self.shutdown.set()
        if self.thread:
            self.thread.join(timeout=5)
        if self.instance_lock and (not self.thread or not self.thread.is_alive()):
            self.instance_lock.close()

    def loop(self):
        while not self.shutdown.is_set():
            try:
                self.tick()
            except Exception as ex:
                self.store.event('执行器已停止当前步骤：' + type(ex).__name__, level='error')
            self.shutdown.wait(2)

    def cancelled(self, ident):
        rows = self.store.rows('SELECT state FROM runs WHERE id=?', (ident,))
        return self.shutdown.is_set() or not rows or rows[0]['state'] != 'running'

    def update(self, run, state, message, due=0):
        with self.store.connect() as db:
            db.execute("UPDATE runs SET state=?,progress=?,message=?,due=?,updated=? WHERE id=? AND state='running'",
                       (state, dumps(run['progress']), message, due, self.clock(), run['id']))
        self.store.event(message, run['id'])

    def tick(self):
        if not self.step_lock.acquire(False):
            return False
        try:
            if revision() != self.cfg.code_revision:
                self.store.stop()
                self.shutdown.set()
                return False
            now = self.clock()
            with self.store.connect(True) as db:
                row = db.execute("SELECT * FROM runs WHERE state IN ('queued','waiting') AND due<=? ORDER BY updated LIMIT 1", (now,)).fetchone()
                if not row:
                    return False
                run = dict(row)
                db.execute("UPDATE runs SET state='running',updated=? WHERE id=?", (now, run['id']))
            run['snapshot'] = json.loads(run['snapshot'])
            run['progress'] = json.loads(run['progress'])
            try:
                snapshot = run['snapshot']
                if snapshot['revision'] != self.cfg.code_revision:
                    raise ValueError('程序已更新，请重新执行以使用新规则')
                for kind in ('account', 'task', 'binding'):
                    old = snapshot[kind]
                    if self.store.get(kind, old['id'])['version'] != old['version']:
                        raise ValueError('配置已变动，请重新执行')
                if self.store.rows('SELECT 1 FROM risk WHERE platform=?', (run['platform'],)):
                    raise ValueError('平台限制尚未解除')
                with self.cfg.browser_lock:
                    self.step(run)
            except Cancelled:
                self.update(run, 'paused', '任务已停止')
            except PlatformRisk as ex:
                self.store.lock(run['platform'], str(ex))
            except (LocalBrowserError, ValueError) as ex:
                self.update(run, 'paused', str(ex))
            except Exception as ex:
                self.update(run, 'failed', '本步骤未完成：' + type(ex).__name__ + '；请检查连接及运行配置')
            return True
        finally:
            self.step_lock.release()

    def step(self, run):
        task, account = run['snapshot']['task'], run['snapshot']['account']
        p, now = run['progress'], self.clock()
        if self.cancelled(run['id']):
            raise Cancelled()
        index = p.get('keyword_index', 0)
        if index >= len(task['keywords']) and not p.get('pending'):
            return self.update(run, 'completed', '任务完成，可在数据中心查看结果')
        if task['kind'] != 'crawler' and p.get('sent', 0) >= task['max_publish']:
            return self.update(run, 'completed', '已达到本任务发布上限')
        if task['kind'] != 'crawler' and p.get('pending'):
            due = comment_due(self.store, run['platform'], task, now)
            if due > now:
                return self.update(run, 'waiting', '等待评论时段或共享发送间隔', due)
        due = read_slot(self.store, run['platform'], now)
        if due > now:
            return self.update(run, 'waiting', '等待平台共享读取间隔或时段', due)
        if task['kind'] == 'crawler':
            items = self.crawler.run(run, task['keywords'][index], lambda: self.cancelled(run['id']))
            for item in items:
                self.store.add_evidence(run['id'], run['platform'], item, 'collected', '爬虫采集；未作为评论目标')
            p.update(keyword_index=index + 1, collected=p.get('collected', 0) + len(items))
            return self.update(run, 'completed' if index + 1 == len(task['keywords']) else 'waiting', f'已采集{p["collected"]}条记录', now+300)
        with self.cfg.browser_factory(account) as browser:
            who = browser.account()
            if str(who.get('id', who.get('account_id', ''))) != account['identity']:
                raise LocalBrowserError('浏览器登录身份与任务绑定不一致，已停止')
            if self.cancelled(run['id']):
                raise Cancelled()
            if not p.get('pending'):
                rows = browser.search(task['keywords'][index])[:task['max_items']]
                pending = []
                for item in rows:
                    ok, reason = assess(task['kind'], item.get('caption', ''))
                    self.store.add_evidence(run['id'], run['platform'], item, 'checking' if ok else 'skipped', reason)
                    if ok and item.get('video_id'):
                        pending.append(item['video_id'])
                p.update(keyword_index=index+1, pending=list(dict.fromkeys(pending)), collected=p.get('collected', 0)+len(rows))
                return self.update(run, 'waiting', f'搜索读取{len(rows)}条，{len(pending)}条等待详情核验', now+300)
            vid = p['pending'].pop(0)
            item = browser.detail(vid)
            ok, reason = detail_ready(task['kind'], item)
            self.store.add_evidence(run['id'], run['platform'], item, 'eligible' if ok else 'skipped', reason)
            if not ok:
                return self.update(run, 'waiting', '自动跳过：' + reason, now+300)
            text = None
            with self.store.connect() as db:
                for candidate in task['templates']:
                    if not contact_reason(db, run['platform'], item, candidate, now):
                        text = candidate
                        break
            if not text:
                return self.update(run, 'waiting', '已跳过：视频、作者或评论文本近期有接触记录', now+300)
            if self.cancelled(run['id']):
                raise Cancelled()
            ident = reserve(self.store, run, item, text, self.clock())
            try:
                if self.cancelled(run['id']):
                    receipt = {'not_sent': True, 'reason': '发送前用户停止'}
                else:
                    receipt = browser.send(item, text)
            except BaseException:
                # A network error after reservation can never prove non-delivery.
                finish(self.store, ident, {'uncertain': True, 'reason': '发送阶段中断，结果未知'})
                raise
            status = finish(self.store, ident, receipt)
            if status == 'sent':
                p['sent'] = p.get('sent', 0) + 1
            self.update(run, 'completed' if p.get('sent', 0) >= task['max_publish'] else 'waiting',
                        receipt.get('reason', '发送步骤结束'), self.clock()+1800)
