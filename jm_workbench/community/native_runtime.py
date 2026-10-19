"""Serialized local desktop execution with a durable last-moment submit guard."""
import contextlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

from ..core.config import revision
from ..core.db import Store,dumps
from .adapters import PreflightStopped,RetryablePreflight,IdentityChanged,NotSubmitted
from .native import NativePublisher,NativeStopped,NativeUnknown,NativeTransient
from .native_channel import NativeChromeChannel


@contextlib.contextmanager
def desktop_lock(home):
    if os.name!='nt':raise RetryablePreflight('本机发布需要Windows可交互桌面')
    import msvcrt
    path=Path(home)/'native-chrome.lock';path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as file:
        file.seek(0);file.write(b'0');file.flush();file.seek(0)
        try:msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise RetryablePreflight('Chrome正在处理另一项工作，本次未提交；稍后重查') from None
        try:yield
        finally:file.seek(0);msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)


def reserve_submit(config,account,payload,target,clock=time.time):
    store=Store(config.home/'jm.db');now=clock();ident=account.get('_native_job_id')
    if not ident:raise PreflightStopped('缺少已持久占位的发布任务，未提交')
    with store.connect(True) as db:
        job=db.execute('SELECT * FROM community_jobs WHERE id=?',(ident,)).fetchone()
        current=db.execute('SELECT * FROM community_accounts WHERE id=?',(account['id'],)).fetchone()
        if job and json.loads(job['receipt']).get('phase')=='native_submit_reserved':
            raise NativeUnknown('本任务已有提交占位，只允许核验，不能判为未发送')
        if not job or job['state']!='running' or job['message'] in ('stop_requested','cancel_requested'):
            raise PreflightStopped('任务已停止或状态变化，未提交')
        snap=json.loads(job['snapshot'])
        if not current or current['version']!=account['version'] or current['identity']!=account['identity'] or not json.loads(current['data'])['enabled']:
            raise IdentityChanged('发布前账号配置变化，未提交')
        if snap['revision']!=revision() or snap['payload']!=payload or snap['destination']!=target:
            raise PreflightStopped('代码、内容或目标变化，未提交')
        if db.execute('SELECT 1 FROM community_risk WHERE platform=?',(account['platform'],)).fetchone():
            raise PreflightStopped('平台已暂停，未提交')
        plan=db.execute('SELECT p.state FROM community_plan_items i JOIN community_plans p ON p.id=i.plan_id WHERE i.post_id=?',(job['post_id'],)).fetchone()
        if plan and plan['state']!='enabled':raise PreflightStopped('每日计划已暂停，未提交')
        receipt=json.loads(job['receipt'])
        recent=list(db.execute("SELECT CASE WHEN started>0 THEN started ELSE updated END AS t FROM community_jobs WHERE platform=? AND id!=? AND (started>? OR (state='recorded' AND updated>?)) ORDER BY t DESC",(account['platform'],ident,now-86400,now-86400)))
        if recent and (now-recent[0]['t']<1800 or len(recent)>=6):raise RetryablePreflight('共享发布间隔或24小时额度未到，本次未提交')
        from .service import SHANGHAI
        midnight=datetime.fromtimestamp(now,SHANGHAI).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        today=list(db.execute("SELECT snapshot FROM community_jobs WHERE platform=? AND id!=? AND (started>=? OR (state='recorded' AND updated>=?))",(account['platform'],ident,midnight,midnight)))
        kind=payload.get('kind','thread')
        if sum(json.loads(r['snapshot'])['payload'].get('kind','thread')==kind for r in today)>=(1 if kind=='thread' else 5):
            raise RetryablePreflight('今日分类发布额度已用，本次未提交')
        db.execute('UPDATE community_jobs SET started=?,receipt=?,updated=? WHERE id=?',(now,dumps({'phase':'native_submit_reserved','submitted':None,'reserved_at':now}),now,ident))


class NativeRuntime:
    def __init__(self,config,channel=NativeChromeChannel):self.config,self.channel=config,channel
    def publisher(self,account,payload=None,target=''):
        if account['platform'] not in ('tieba','juejin','zhihu'):raise PreflightStopped('此平台未接入本机自动发布')
        if not account.get('native_binding'):raise PreflightStopped('请先核验此账号的本人主页')
        root=self.config.home/'native-tabs'
        identity=self.channel(root/(account['id']+'-identity.json'))
        identity.readonly_replacement=True
        return NativePublisher(self.channel(root/(account['id']+'-publish.json')),
            identity_ui=identity,
            before_submit=lambda:reserve_submit(self.config,account,payload,target))
    def check(self,account):
        with desktop_lock(self.config.home):
            try:return self.publisher(account).check(account,account['native_binding'])
            except NativeStopped as ex:raise RetryablePreflight(str(ex)) from None
    def publish(self,account,payload,target):
        with desktop_lock(self.config.home):
            publisher=self.publisher(account,payload,target);entered=False
            # Only a new article with no unresolved draft may replace yesterday's
            # repurposed task tab. The existing tab and browser profile stay intact.
            if hasattr(publisher,'ui') and payload.get('kind','thread')=='thread':
                publisher.ui.preflight_replacement=True
            reserve=publisher.before_submit
            def mark_submission():
                nonlocal entered
                reserve();entered=True
            publisher.before_submit=mark_submission
            try:return publisher.publish(account,account['native_binding'],payload,target)
            except NativeUnknown:raise
            except NotSubmitted:raise
            except NativeStopped as ex:
                if entered:raise NativeUnknown('已进入提交边界，页面核验暂未完成；保留原回执，不自动重发') from ex
                if isinstance(ex,NativeTransient):raise RetryablePreflight(str(ex)) from None
                if '其他窗口遮挡目标控件' in str(ex):
                    raise RetryablePreflight('窗口暂时遮挡发布控件，本次未提交；稍后重查') from None
                raise PreflightStopped(str(ex)) from None
            except Exception as ex:
                if not entered:raise PreflightStopped('本机准备发生'+type(ex).__name__+'，尚未进入提交；原内容保留') from ex
                raise
    def discover(self,account,terms):
        from .native_discovery import NativeDiscovery
        if account['platform'] not in ('tieba','juejin','zhihu'):raise PreflightStopped('此平台尚未接入本机原帖发现')
        with desktop_lock(self.config.home):
            try:
                channel=self.channel(self.config.home/'native-tabs'/(account['id']+'-discover.json'))
                return NativeDiscovery(channel).discover(account,terms)
            except NativeStopped as ex:raise RetryablePreflight('相关原帖读取暂未完成，稍后重查；未提交内容') from ex
