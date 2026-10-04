import hashlib
import json
import sqlite3
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from contextlib import nullcontext
from pathlib import Path
from ..core.db import dumps, uid
from ..core.config import revision
from .adapters import CommunityAdapter, NotSubmitted, PreflightStopped
from .registry import PLATFORMS, platform, destination, compose_url, safe_post_url, tieba_thread_url, thread_url
from .secrets import seal, unseal

ACTIVE = ('queued','running','paused','unknown','manual')
SHANGHAI = timezone(timedelta(hours=8))


def content_key(text):
    value=''.join(c for c in unicodedata.normalize('NFKC',text).casefold() if c.isalnum())
    return hashlib.sha256(value.encode()).hexdigest()


class Community:
    def __init__(self,cfg,adapter=None,clock=time.time):
        self.cfg,self.store,self.clock=cfg,cfg.store,clock
        self.adapter=adapter or CommunityAdapter(cfg.config)
        self.shutdown=threading.Event();self.step_lock=threading.Lock();self.thread=None
        with self.store.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS community_accounts(id TEXT PRIMARY KEY, data TEXT,
              credential TEXT DEFAULT '', version INTEGER DEFAULT 1, identity TEXT DEFAULT '', checked REAL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS community_posts(id TEXT PRIMARY KEY, request_id TEXT UNIQUE,
              payload TEXT, state TEXT DEFAULT 'draft', created REAL, updated REAL);
            CREATE TABLE IF NOT EXISTS community_jobs(id TEXT PRIMARY KEY, post_id TEXT, platform TEXT,
              account_id TEXT, identity TEXT, digest TEXT, state TEXT, snapshot TEXT,
              receipt TEXT DEFAULT '{}', message TEXT DEFAULT '', due REAL, started REAL DEFAULT 0, created REAL, updated REAL);
            CREATE UNIQUE INDEX IF NOT EXISTS community_once ON community_jobs(platform,identity,digest)
              WHERE state IN ('queued','running','paused','submitted','unknown','manual','recorded');
            CREATE TABLE IF NOT EXISTS community_risk(platform TEXT PRIMARY KEY, reason TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS community_claims(platform TEXT, identity TEXT, scope TEXT,
              value TEXT, job_id TEXT, created REAL, PRIMARY KEY(platform,identity,scope,value));
            ''')
            # Add an index of historical writes without changing their snapshots.
            for row in db.execute("SELECT id,platform,identity,snapshot,created FROM community_jobs WHERE platform IN ('tieba','juejin','csdn') AND state IN ('queued','running','paused','submitted','unknown','manual','recorded')").fetchall():
                snap=json.loads(row['snapshot']);payload=snap['payload']
                keys=[('content',content_key(payload['body']))]
                if payload.get('kind')=='reply':keys.append(('reply_target',thread_url(row['platform'],snap['destination'])))
                for scope,value in keys:
                    db.execute('INSERT OR IGNORE INTO community_claims VALUES(?,?,?,?,?,?)',(row['platform'],row['identity'],scope,value,row['id'],row['created']))
        from .daily import DailyPlans
        self.daily=DailyPlans(self)

    def account(self,ident,private=False):
        rows=self.store.rows('SELECT * FROM community_accounts WHERE id=?',(ident,))
        if not rows:raise ValueError('社区账号不存在')
        row=rows[0]
        value={**json.loads(row['data']),'id':row['id'],'version':row['version'],'identity':row['identity'],
               'checked':row['checked'],'secret_configured':bool(row['credential'])}
        if private:
            value['profile_dir']=str(self.cfg.config.home/'community-profiles'/ident)
            value['_secret']=unseal(row['credential'])
        return value

    def save_account(self,payload,ident=None):
        editing=ident is not None
        ident=ident or uid();data=payload.model_dump(exclude={'secret'})
        secret=payload.secret.get_secret_value()
        encrypted=seal(secret) if secret else ''
        with self.store.connect(True) as db:
            old=db.execute('SELECT * FROM community_accounts WHERE id=?',(ident,)).fetchone()
            if editing and not old:raise ValueError('社区账号不存在，请刷新列表')
            if db.execute("SELECT 1 FROM community_jobs WHERE account_id=? AND state IN ('queued','running','paused','unknown','manual')",(ident,)).fetchone():
                raise ValueError('该账号仍有活动或不确定的发帖任务，请先处理任务')
            if db.execute("SELECT 1 FROM community_plans WHERE state='enabled' AND json_extract(payload,'$.account_id')=?",(ident,)).fetchone():
                raise ValueError('该账号仍有启用的每日计划，请先暂停计划')
            if old and json.loads(old['data'])['platform']!=data['platform']:
                raise ValueError('已有账号不能更换平台，请另建账号')
            if old:
                db.execute("UPDATE community_accounts SET data=?,credential=?,version=version+1,identity='',checked=0 WHERE id=?",(dumps(data),encrypted or old['credential'],ident))
            else:
                db.execute('INSERT INTO community_accounts(id,data,credential) VALUES(?,?,?)',(ident,dumps(data),encrypted))
        return self.account(ident)

    def delete_account(self,ident,version):
        # Serialize with draft saves and launch, so no dangling targets can appear.
        with self.store.connect(True) as db:
            a=db.execute('SELECT version FROM community_accounts WHERE id=?',(ident,)).fetchone()
            if not a:return {'id':ident,'deleted':True,'message':'社区账号已删除'}
            if a['version']!=version:raise ValueError('账号配置已改变，请刷新后重新确认删除')
            if db.execute("SELECT 1 FROM community_plans WHERE json_extract(payload,'$.account_id')=?",(ident,)).fetchone():
                raise ValueError('该账号被每日计划引用，请使用停用保留记录')
            if db.execute('SELECT 1 FROM community_jobs WHERE account_id=?',(ident,)).fetchone():
                raise ValueError('该账号已有发帖任务或历史记录，请使用“编辑 → 停用”保留记录')
            for row in db.execute('SELECT state,payload FROM community_posts'):
                if any(t['account_id']==ident for t in json.loads(row['payload'])['targets']):
                    if row['state']=='draft':raise ValueError('该账号被草稿引用，请先编辑草稿移除该账号，再删除')
                    raise ValueError('该账号已有帖子记录，请使用“编辑 → 停用”保留记录')
            db.execute('DELETE FROM community_accounts WHERE id=?',(ident,))
        # This only removes local configuration, never the browser profile or platform account.
        return {'id':ident,'deleted':True,'message':'社区账号已删除，浏览器登录资料保留'}

    def check_account(self,ident):
        a=self.account(ident,True)
        if not a['enabled']:raise ValueError('请先启用此账号')
        try:identity=self.adapter.check(a,a['_secret'])
        except Exception as ex:
            message=str(ex) if isinstance(ex,NotSubmitted) else '账号检查未完成，请确认登录、API权限或网络'
            raise ValueError(message) from None
        if a['identity'] and a['identity']!=identity:
            raise ValueError('登录身份已变化，请重新配置账号；不能替换原任务的身份')
        with self.store.connect(True) as db:
            current=db.execute('SELECT version,identity FROM community_accounts WHERE id=?',(ident,)).fetchone()
            if not current or current['version']!=a['version']:
                raise ValueError('核验期间账号配置已改变，请重新检查')
            if current['identity'] and current['identity']!=identity:
                raise ValueError('登录身份已变化，请重新配置账号；不能替换原任务的身份')
            db.execute('UPDATE community_accounts SET identity=?,checked=? WHERE id=?',(identity,self.clock(),ident))
            # Preserve historical web registration while binding its content claims to the verified identity.
            db.execute('INSERT OR IGNORE INTO community_claims SELECT platform,?,scope,value,job_id,created FROM community_claims WHERE platform=? AND identity=?',(identity,a['platform'],'manual:'+ident))
        return {'message':'账号身份已核验；发帖权限会在实际提交时由平台校验','account':self.account(ident)}

    def sync_account(self,ident):
        a=self.account(ident)
        if a['platform'] not in ('tieba','juejin','csdn') or not a['enabled']:
            raise ValueError('自动同步仅适用于已启用的贴吧、掘金或CSDN浏览器账号')
        try:return {'status':'verified',**self.check_account(ident)}
        except ValueError as ex:return {'status':'pending','message':str(ex)}

    def open_account(self,ident):
        a=self.account(ident,True)
        return self.adapter.open(a,platform(a['platform'])['home'])

    def save(self,payload,ident=None,_db=None):
        data=payload.model_dump();now=self.clock()
        if data['schedule_at'] and data['schedule_at']<=now:raise ValueError('请选择未来的发布时间')
        with (self.store.connect(True) if _db is None else nullcontext(_db)) as db:
            for target in data['targets']:
                if not db.execute('SELECT 1 FROM community_accounts WHERE id=?',(target['account_id'],)).fetchone():
                    raise ValueError('社区账号不存在，请刷新后重新选择发布账号')
            if ident:
                old=db.execute('SELECT * FROM community_posts WHERE id=?',(ident,)).fetchone()
                if not old or old['state']!='draft':raise ValueError('仅未启动的草稿可以编辑')
                if old['request_id']!=data['request_id']:raise ValueError('草稿标识不一致')
                db.execute('UPDATE community_posts SET payload=?,updated=? WHERE id=?',(dumps(data),now,ident))
            else:
                old=db.execute('SELECT * FROM community_posts WHERE request_id=?',(data['request_id'],)).fetchone()
                if old:
                    if json.loads(old['payload'])!=data:raise ValueError('请求标识已被其他草稿使用')
                    return {'id':old['id'],'message':'草稿已保存'}
                ident=uid()
                db.execute('INSERT INTO community_posts(id,request_id,payload,created,updated) VALUES(?,?,?,?,?)',(ident,data['request_id'],dumps(data),now,now))
        return {'id':ident,'message':'草稿已保存，尚未发布'}

    def launch(self,ident,_db=None):
        now=self.clock()
        try:
            with (self.store.connect(True) if _db is None else nullcontext(_db)) as db:
                row=db.execute('SELECT * FROM community_posts WHERE id=?',(ident,)).fetchone()
                if not row:raise ValueError('帖子不存在')
                if row['state']!='draft':return {'id':ident,'message':'该帖子已经创建发布任务，请查看记录'}
                payload=json.loads(row['payload'])
                planned=[]
                for t in payload['targets']:
                    raw=db.execute('SELECT * FROM community_accounts WHERE id=?',(t['account_id'],)).fetchone()
                    if not raw:raise ValueError('社区账号不存在')
                    a={**json.loads(raw['data']),'id':raw['id'],'version':raw['version'],'identity':raw['identity'],'checked':raw['checked']}
                    kind=payload.get('kind','thread')
                    if kind=='reply' and a['platform'] not in ('tieba','juejin','csdn'):raise ValueError('当前仅百度贴吧、掘金、CSDN支持评论发布')
                    p=platform(a['platform']);dest=thread_url(a['platform'],t['destination']) if kind=='reply' else destination(a['platform'],t['destination'])
                    if not a['enabled']:raise ValueError(a['name']+'：账号已停用')
                    if len(payload['title'])>p['title_limit']:raise ValueError(p['name']+'标题过长')
                    if a['platform']=='tieba' and ((kind=='thread' and len(payload['title'])<5) or len(payload['body'])>2000):raise ValueError('贴吧标题需5–31字，正文最多2000字')
                    if a['platform']=='csdn':
                        from .csdn import validate_payload
                        validate_payload(payload,dest)
                    if a['platform']=='juejin':
                        from .juejin import validate_payload
                        validate_payload(payload,dest)
                    if a['platform']=='x' and len(payload['title']+'\n\n'+payload['body'])>280:raise ValueError('X标题与正文合计最多280字符')
                    if a['platform']=='huggingface' and len(payload['title'])<3:raise ValueError('Hub标题至少3个字符')
                    if a['platform']=='dev' and payload['body'].lstrip().startswith('---'):raise ValueError('DEV正文不能以YAML配置头开头')
                    if p['automatic']:
                        if db.execute('SELECT 1 FROM community_risk WHERE platform=?',(a['platform'],)).fetchone():raise ValueError(p['name']+'发布已暂停，请先核实平台限制或结果不明记录')
                        if not a['identity'] or now-a['checked']>86400:raise ValueError(a['name']+'：请先检查账号登录身份')
                        if p['mode']=='api' and not raw['credential']:raise ValueError(a['name']+'：请配置API授权')
                    identity=a['identity'] or 'manual:'+a['id']
                    digest=hashlib.sha256(dumps([dest,payload['title'],payload['body'],payload['tags']]).encode()).hexdigest()
                    snapshot={'account':a,'payload':payload,'destination':dest,'revision':self.cfg.code_revision}
                    job_id=uid()
                    if a['platform'] in ('tieba','juejin','csdn'):
                        keys=[('content',content_key(payload['body']))]
                        if kind=='reply':keys.append(('reply_target',dest))
                        for scope,value in keys:
                            db.execute('INSERT INTO community_claims VALUES(?,?,?,?,?,?)',(a['platform'],identity,scope,value,job_id,now))
                    planned.append((job_id,ident,a['platform'],a['id'],identity,digest,'queued' if p['automatic'] else 'manual',dumps(snapshot),max(now,payload['schedule_at']),now,now))
                db.executemany('INSERT INTO community_jobs(id,post_id,platform,account_id,identity,digest,state,snapshot,due,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)',planned)
                db.execute("UPDATE community_posts SET state='active',updated=? WHERE id=?",(now,ident))
        except sqlite3.IntegrityError:
            raise ValueError('存在同账号、同板块、同内容的重复任务，已阻止重复发布') from None
        return {'id':ident,'message':'已创建发布任务；网页发布目标需在对应网站完成提交'}

    def jobs(self,post_id):
        result=[]
        for r in self.store.rows('SELECT * FROM community_jobs WHERE post_id=? ORDER BY created,rowid',(post_id,)):
            snapshot=json.loads(r.pop('snapshot'));r['receipt']=json.loads(r['receipt'])
            r.update(account_name=snapshot['account']['name'],destination=snapshot['destination'])
            result.append(r)
        return result

    def state(self):
        posts=[]
        for r in self.store.rows('SELECT * FROM community_posts ORDER BY created DESC,rowid DESC LIMIT 200'):
            r['payload']=json.loads(r['payload']);r['jobs']=self.jobs(r['id']);posts.append(r)
        return {'platforms':list(PLATFORMS.values()),'accounts':[self.account(r['id']) for r in self.store.rows('SELECT id FROM community_accounts ORDER BY rowid')],
                'posts':posts,'plans':self.daily.state(),'risk':self.store.rows('SELECT * FROM community_risk'),
                'worker':bool(self.thread and self.thread.is_alive()),'limits':{'interval_seconds':1800,'per_platform_24h':5,**{p:{'per_24h':6,'threads_per_day':1,'replies_per_day':5,'timezone':'Asia/Shanghai'} for p in ('tieba','juejin','csdn')}}}

    def control(self,ident,action):
        now=self.clock()
        with self.store.connect(True) as db:
            if not db.execute('SELECT 1 FROM community_posts WHERE id=?',(ident,)).fetchone():raise ValueError('帖子不存在')
            if action=='pause':
                db.execute("UPDATE community_jobs SET state='paused',message='用户暂停',updated=? WHERE post_id=? AND state='queued'",(now,ident))
                db.execute("UPDATE community_jobs SET message='stop_requested' WHERE post_id=? AND state='running'",(ident,))
            elif action=='cancel':
                db.execute("UPDATE community_jobs SET state='cancelled',message='用户取消',updated=? WHERE post_id=? AND state IN ('queued','paused','manual')",(now,ident))
                db.execute("UPDATE community_posts SET state='cancelled',updated=? WHERE id=? AND state='draft'",(now,ident))
                db.execute("UPDATE community_jobs SET message='cancel_requested' WHERE post_id=? AND state='running'",(ident,))
            elif action=='resume':
                for r in db.execute("SELECT platform,snapshot FROM community_jobs WHERE post_id=? AND state='paused'",(ident,)):
                    if db.execute('SELECT 1 FROM community_risk WHERE platform=?',(r['platform'],)).fetchone():raise ValueError('平台仍有限制或结果不明，不能继续')
                    snapshot=json.loads(r['snapshot']);a=db.execute('SELECT version FROM community_accounts WHERE id=?',(snapshot['account']['id'],)).fetchone()
                    if a['version']!=snapshot['account']['version'] or snapshot['revision']!=self.cfg.code_revision:raise ValueError('原任务配置已失效，请新建草稿')
                db.execute("UPDATE community_jobs SET state='queued',message='',updated=? WHERE post_id=? AND state='paused'",(now,ident))
            else:raise ValueError('不支持的操作')
        return {'message':{'pause':'任务已暂停','cancel':'未提交的目标已取消','resume':'任务已继续'}[action]}

    def stop_all(self):
        with self.store.connect(True) as db:
            db.execute("UPDATE community_plans SET state='paused',message='用户停止全部任务',updated=? WHERE state='enabled'",(self.clock(),))
            db.execute("UPDATE community_jobs SET state='paused',message='用户停止全部任务',updated=? WHERE state='queued'",(self.clock(),))
            db.execute("UPDATE community_jobs SET message='stop_requested' WHERE state='running'")

    def retry_preflight(self,ident):
        with self.step_lock:
            rows=self.store.rows('SELECT * FROM community_jobs WHERE id=?',(ident,))
            if not rows:raise ValueError('任务不存在')
            job=rows[0];receipt=json.loads(job['receipt']);snap=json.loads(job['snapshot'])
            if job['state']!='failed' or receipt.get('phase')!='preflight' or receipt.get('submitted') is not False:
                raise ValueError('只有明确未进入提交的本地预检失败可重新检查；平台拒绝和结果不明不能重发')
            self.check_account(job['account_id']);a=self.account(job['account_id'])
            with self.store.connect(True) as db:
                current=db.execute('SELECT state,receipt FROM community_jobs WHERE id=?',(ident,)).fetchone()
                if current['state']!='failed' or current['receipt']!=job['receipt']:raise ValueError('任务已变化，请刷新')
                if db.execute('SELECT 1 FROM community_risk WHERE platform=?',(job['platform'],)).fetchone():raise ValueError('平台仍有暂停记录，不能重试')
                if a['identity']!=snap['account']['identity'] or a['version']!=snap['account']['version'] or snap['revision']!=self.cfg.code_revision:
                    raise ValueError('原账号或代码快照已失效，不能重试')
                history=receipt.get('preflight_history',[])+[{'message':job['message'],'at':job['updated']}]
                db.execute("UPDATE community_jobs SET state='queued',started=0,due=?,message='本地预检已复核，继续原任务',receipt=?,updated=? WHERE id=?",(self.clock(),dumps({'preflight_history':history}),self.clock(),ident))
            return {'message':'已继续原任务；没有新建重复内容'}

    def resolve(self,ident,outcome,note,url=''):
        if len(note.strip())<12 or outcome not in ('submitted','not_sent'):raise ValueError('请填写完整的核实结果')
        job=self.job(ident)
        receipt={'note':note,'visibility':'user_reported'}
        if outcome=='submitted':receipt['url']=safe_post_url(job['platform'],url)
        with self.store.connect(True) as db:
            if db.execute('SELECT state FROM community_jobs WHERE id=?',(ident,)).fetchone()['state']!='unknown':raise ValueError('仅结果不明记录需要此处理')
            db.execute('UPDATE community_jobs SET state=?,receipt=?,message=?,updated=? WHERE id=?',('recorded' if outcome=='submitted' else 'not_sent',dumps(receipt),'用户核实：'+note,self.clock(),ident))
        return {'message':'核实结果已记录，没有自动重发；平台暂停需单独处理'}

    def clear_risk(self,p,note):
        platform(p)
        if len(note.strip())<12:raise ValueError('请填写至少12字的处理说明')
        with self.store.connect(True) as db:
            if db.execute("SELECT 1 FROM community_jobs WHERE platform=? AND state IN ('running','unknown')",(p,)).fetchone():raise ValueError('仍有提交中或结果不明的记录，请先逐条核实')
            db.execute('DELETE FROM community_risk WHERE platform=?',(p,))
        self.store.event('社区平台解除记录：'+platform(p)['name']+'；'+note)
        return {'message':'已记录并解除平台暂停；任务仍保持暂停，需主动继续'}

    def job(self,ident):
        rows=self.store.rows('SELECT * FROM community_jobs WHERE id=?',(ident,))
        if not rows:raise ValueError('发布记录不存在')
        r=rows[0];r['snapshot']=json.loads(r['snapshot']);return r

    def open_job(self,ident):
        job=self.job(ident);s=job['snapshot']
        url=json.loads(job['receipt']).get('url') or compose_url(job['platform'],s['destination'])
        return self.adapter.open(self.account(job['account_id'],True),url)

    def record_url(self,ident,url):
        job=self.job(ident)
        url=safe_post_url(job['platform'],url)
        with self.store.connect(True) as db:
            r=db.execute('SELECT state FROM community_jobs WHERE id=?',(ident,)).fetchone()
            if r['state']!='manual':raise ValueError('仅网页待发布记录支持登记链接')
            db.execute("UPDATE community_jobs SET state='recorded',receipt=?,message='用户登记链接 · 未核验公开可见',updated=? WHERE id=?",(dumps({'url':url,'visibility':'user_reported'}),self.clock(),ident))
        return {'message':'链接已登记，公开可见性尚未核验'}

    def lock_platform(self,p,reason,db):
        db.execute('INSERT OR REPLACE INTO community_risk VALUES(?,?,?)',(p,reason,self.clock()))
        db.execute("UPDATE community_jobs SET state='paused',message=?,updated=? WHERE platform=? AND state='queued'",(reason,self.clock(),p))
        db.execute("UPDATE community_plans SET state='paused',message=?,updated=? WHERE state='enabled' AND json_extract(payload,'$.account_id') IN (SELECT id FROM community_accounts WHERE json_extract(data,'$.platform')=?)",(reason,self.clock(),p))

    def recover(self):
        self.daily.recover()
        with self.store.connect(True) as db:
            platforms=[r['platform'] for r in db.execute("SELECT DISTINCT platform FROM community_jobs WHERE state='running'")]
            db.execute("UPDATE community_jobs SET state='unknown',message='服务中断，提交结果不明，请到平台核实',updated=? WHERE state='running'",(self.clock(),))
            for p in platforms:self.lock_platform(p,'服务中断后存在结果不明的发帖记录',db)

    def tick(self):
        if not self.step_lock.acquire(blocking=False):return
        try:self._tick()
        finally:self.step_lock.release()

    def _tick(self):
        now=self.clock()
        if self.cfg.code_revision!=revision():return
        self.daily.tick()
        with self.store.connect(True) as db:
            job=db.execute("SELECT * FROM community_jobs WHERE state='queued' AND due<=? ORDER BY due,created,rowid LIMIT 1",(now,)).fetchone()
            if not job:return
            job=dict(job);s=json.loads(job['snapshot']);p=job['platform']
            if db.execute('SELECT 1 FROM community_risk WHERE platform=?',(p,)).fetchone():
                db.execute("UPDATE community_jobs SET state='paused',message='平台已暂停' WHERE id=?",(job['id'],));return
            raw=db.execute('SELECT * FROM community_accounts WHERE id=?',(job['account_id'],)).fetchone()
            if not raw or raw['version']!=s['account']['version'] or not json.loads(raw['data'])['enabled'] or s['revision']!=self.cfg.code_revision:
                db.execute("UPDATE community_jobs SET state='paused',message='配置或代码版本已改变，请新建草稿' WHERE id=?",(job['id'],));return
            recent=list(db.execute("SELECT CASE WHEN started>0 THEN started WHEN state='recorded' THEN updated ELSE 0 END AS started FROM community_jobs WHERE platform=? AND (CASE WHEN started>0 THEN started WHEN state='recorded' THEN updated ELSE 0 END)>? ORDER BY started DESC",(p,now-86400)))
            limit=6 if p in ('tieba','juejin','csdn') else 5
            due=max((recent[0]['started']+1800 if recent else now),(recent[limit-1]['started']+86400 if len(recent)>=limit else now))
            if p in ('tieba','juejin','csdn'):
                midnight=datetime.fromtimestamp(now,SHANGHAI).replace(hour=0,minute=0,second=0,microsecond=0)
                today=list(db.execute("SELECT snapshot FROM community_jobs WHERE platform=? AND (started>=? OR (state='recorded' AND updated>=?))",(p,midnight.timestamp(),midnight.timestamp())))
                kind=s['payload'].get('kind','thread')
                used=sum(json.loads(r['snapshot'])['payload'].get('kind','thread')==kind for r in today)
                if used>=(1 if kind=='thread' else 5):due=max(due,(midnight+timedelta(days=1)).timestamp())
            if due>now:
                db.execute("UPDATE community_jobs SET due=?,message='等待平台共享发布间隔/每日额度' WHERE id=?",(due,job['id']));return
            db.execute("UPDATE community_jobs SET state='running',started=?,updated=?,message='正在检查账号并提交' WHERE id=?",(now,now,job['id']))
        receipt={}
        try:
            a=self.account(job['account_id'],True)
            # Any failure during this read-only stage is definitively no submission.
            try:
                identity=self.adapter.check(a,a['_secret'])
                if identity!=s['account']['identity']:raise NotSubmitted('登录身份已变化，未提交')
            except Exception:
                raise PreflightStopped('账号预检失败或身份变化，未提交；请检查登录和授权') from None
            if self.shutdown.is_set():raise NotSubmitted('服务正在停止，尚未提交')
            current=self.store.rows('SELECT message FROM community_jobs WHERE id=?',(job['id'],))[0]
            if current['message'] in ('stop_requested','cancel_requested'):raise InterruptedError(current['message'])
            receipt=self.adapter.publish(a,a['_secret'],s['payload'],s['destination'])
            if not receipt.get('post_id') or not receipt.get('url'):raise RuntimeError('missing receipt')
            safe_post_url(p,receipt['url'])
            status,message='submitted','平台已接收 · 公开可见性未核验'
        except InterruptedError as ex:
            status,message=('cancelled' if str(ex)=='cancel_requested' else 'paused'),'用户已停止，未提交'
        except PreflightStopped as ex:
            status,message='failed',str(ex)
            receipt={'phase':'preflight','submitted':False}
        except NotSubmitted as ex:
            status,message='failed',str(ex)
        except Exception:
            status,message='unknown','提交结果不明，已暂停此平台；请到网站核实，禁止自动重发'
        with self.store.connect(True) as db:
            db.execute('UPDATE community_jobs SET state=?,receipt=?,message=?,updated=? WHERE id=?',(status,dumps(receipt),message,self.clock(),job['id']))
            if status=='failed' and receipt.get('phase')=='preflight':
                db.execute('UPDATE community_jobs SET started=0 WHERE id=?',(job['id'],))
                db.execute("UPDATE community_jobs SET state='paused',message=? WHERE platform=? AND state='queued'",(message,p))
                db.execute("UPDATE community_plans SET state='paused',message=?,updated=? WHERE state='enabled' AND json_extract(payload,'$.account_id') IN (SELECT id FROM community_accounts WHERE json_extract(data,'$.platform')=?)",(message,self.clock(),p))
            elif status in ('unknown','failed'):self.lock_platform(p,message,db)

    def start(self):
        self.recover()
        self.thread=threading.Thread(target=self.run,name='jm-community',daemon=True);self.thread.start()

    def run(self):
        while not self.shutdown.is_set():
            try:self.tick()
            except Exception:self.store.event('社区执行器本地异常，稍后检查；不自动重发已占位请求',level='error')
            self.shutdown.wait(3)

    def close(self):
        self.shutdown.set()
        if self.thread:self.thread.join(timeout=2)
