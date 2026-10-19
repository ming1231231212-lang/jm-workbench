"""Durable daily planning. A shortage is recorded, never filled with unrelated replies."""
import hashlib
import json
import threading
from datetime import datetime, timedelta
from .models import CommunityPost
from .registry import thread_url, destination, tag_label
from .adapters import IdentityChanged
from ..core.db import dumps,uid


def material_id(body):
    from .service import content_key
    return content_key(body)


def eligible(rule,candidate):
    import re
    text=(candidate['title']+'\n'+candidate['excerpt']).casefold()
    if len(candidate['excerpt'].strip())<15:return False
    if re.search(r'网盘|代充|返佣|加群|拼团|加微|招代理|破解版|购买链接',text):return False
    if not all(word.casefold() in text for word in rule['terms']):return False
    # Keywords scattered across a long article do not establish one relevant topic.
    if not rule['require_question']:
        parts=re.split(r'[\n。.!！?？]',text)
        return any(len(part)<=240 and all(word.casefold() in part for word in rule['terms']) for part in parts)
    # A question elsewhere in a long article is not evidence of this problem.
    # Keep the matching terms and the question in the same concrete sentence.
    sentences=re.findall(r'[^\n。.!！?？]+[。.!！?？]?',text)
    return any(len(part)<=240 and all(word.casefold() in part for word in rule['terms'])
               and re.search(r'怎么|如何|哪里|哪个|求助|求推荐|有没有|请教|[?？]',part) for part in sentences)


class DailyPlans:
    def __init__(self,community):
        self.s=community;self.store=community.store;self.lock=threading.RLock()
        with self.store.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS community_plans(id TEXT PRIMARY KEY,payload TEXT,state TEXT,
              identity TEXT,account_version INTEGER,revision TEXT,message TEXT,created REAL,updated REAL);
            CREATE TABLE IF NOT EXISTS community_plan_days(plan_id TEXT,day TEXT,state TEXT,message TEXT,
              created REAL,updated REAL,PRIMARY KEY(plan_id,day));
            CREATE TABLE IF NOT EXISTS community_plan_items(plan_id TEXT,day TEXT,kind TEXT,material TEXT,
              post_id TEXT,PRIMARY KEY(plan_id,material),UNIQUE(post_id));
            CREATE TABLE IF NOT EXISTS community_plan_checks(plan_id TEXT,day TEXT,next_check REAL,
              attempts INTEGER,reply_goal INTEGER,PRIMARY KEY(plan_id,day));
            ''')

    def get(self,ident):
        rows=self.store.rows('SELECT * FROM community_plans WHERE id=?',(ident,))
        if not rows:raise ValueError('每日计划不存在')
        r=rows[0];r['payload']=json.loads(r['payload']);return r

    def day_jobs(self,p,day,*,scheduled=False):
        """Execution-day progress, while the original plan item stays immutable."""
        from .service import SHANGHAI
        rows=self.store.rows('''SELECT i.kind,i.day,i.post_id,j.state,j.started,j.updated,j.receipt
            FROM community_plan_items i JOIN community_jobs j ON j.post_id=i.post_id
            WHERE i.plan_id=? AND j.account_id=? AND j.rowid=(SELECT x.rowid FROM community_jobs x
              WHERE x.post_id=j.post_id AND x.account_id=j.account_id ORDER BY x.created DESC,x.rowid DESC LIMIT 1)''',
            (p['id'],p['payload']['account_id']))
        result=[]
        for row in rows:
            effective=row['day']
            if not scheduled and row['state'] in ('submitted','recorded') and json.loads(row['receipt']).get('url'):
                stamp=row['started'] if row['state']=='submitted' else row['updated']
                if stamp>0:effective=datetime.fromtimestamp(stamp,SHANGHAI).date().isoformat()
            if effective==day:result.append(row)
        return result

    @staticmethod
    def counts(jobs):
        return {k:{'planned':sum(j['kind']==k for j in jobs),
            'submitted':sum(j['kind']==k and j['state']=='submitted' for j in jobs),
            'recorded':sum(j['kind']==k and j['state']=='recorded' for j in jobs),
            'waiting':sum(j['kind']==k and j['state'] in ('queued','paused') for j in jobs),
            'failed':sum(j['kind']==k and j['state'] in ('failed','unknown') for j in jobs)} for k in ('thread','reply')}

    def state(self):
        plans=[]
        for row in self.store.rows('SELECT id FROM community_plans ORDER BY created DESC'):
            p=self.get(row['id']);items=self.store.rows('SELECT * FROM community_plan_items WHERE plan_id=?',(p['id'],))
            used={i['material'] for i in items}
            p['remaining_topics']=sum(material_id(t['body']) not in used for t in p['payload']['topics'])
            p['remaining_replies']=sum(material_id(t['body']) not in used for t in p['payload']['replies']+p['payload']['reply_rules'])
            days=self.store.rows('SELECT * FROM community_plan_days WHERE plan_id=? ORDER BY day DESC LIMIT 14',(p['id'],))
            for d in days:
                checks=self.store.rows('SELECT next_check,attempts,reply_goal FROM community_plan_checks WHERE plan_id=? AND day=?',(p['id'],d['day']))
                d.update(checks[0] if checks else {'next_check':0,'attempts':0,'reply_goal':5})
                d['counts']=self.counts(self.day_jobs(p,d['day']))
                d['scheduled_counts']=self.counts(self.day_jobs(p,d['day'],scheduled=True))
            p['platform']=self.s.account(p['payload']['account_id'])['platform'];p['days']=days
            p['preparations']=self.s.materials.state(p['id']) if hasattr(self.s,'materials') else []
            for batch in p['preparations']:
                pool=self.s.materials.pool(p,batch['day']);batch['materials']=pool
            from .service import SHANGHAI
            now=self.s.clock();local=datetime.fromtimestamp(now,SHANGHAI);today=local.date().isoformat()
            current=next((d for d in days if d['day']==today),None)
            p['next_action_at']=0;p['next_action']='已暂停，等待主动启用'
            if self.s.account(p['payload']['account_id']).get('automatic_execution') is False:
                p['next_action']='当前使用网页发布，每日自动发布已停用';p['next_send_at']=0
            elif p['state']=='enabled':
                queued=self.store.rows("SELECT j.due,j.message FROM community_jobs j JOIN community_plan_items i ON i.post_id=j.post_id WHERE i.plan_id=? AND j.state='queued' ORDER BY j.due LIMIT 1",(p['id'],))
                times=[]
                if queued:times.append((max(now,queued[0]['due']),queued[0]['message'] or '执行已安排的任务'))
                if current and current['next_check']:times.append((max(now,current['next_check']),'重新检查素材、目标与账号连接'))
                start=local.replace(hour=p['payload']['hour'],minute=p['payload']['minute'],second=0,microsecond=0)
                if current:start+=timedelta(days=1)
                if p['payload'].get('start_date'):
                    start=max(start,datetime.fromisoformat(p['payload']['start_date']).replace(tzinfo=SHANGHAI,hour=p['payload']['hour'],minute=p['payload']['minute']))
                if p['payload'].get('auto_prepare'):
                    prepared=next((b for b in p['preparations'] if b['day']==start.date().isoformat()),None)
                    if not prepared:times.append((max(now,(start-timedelta(hours=1)).timestamp()),'自动准备文章和相关原帖评论' if p['payload'].get('replies_per_day',5) else '自动准备文章'))
                    elif prepared['state']!='ready':times.append((max(now,prepared['next_check'] or (start-timedelta(hours=1)).timestamp()),'继续准备内容并核对素材缺口'))
                times.append((max(now,start.timestamp()),'安排每日任务'))
                p['next_action_at'],p['next_action']=min(times,key=lambda t:t[0])
                p['next_send_at']=max(now,queued[0]['due']) if queued else 0
            plans.append(p)
        return plans

    def save(self,payload,ident=None):
        data=payload.model_dump(mode='json');now=self.s.clock()
        a=self.s.account(data['account_id'])
        if a['platform'] not in ('tieba','juejin','csdn','zhihu'):raise ValueError('此平台尚未接入每日评论计划')
        if data.get('auto_prepare') and (a['platform'] not in ('tieba','juejin','zhihu') or self.s.cfg.config.values.get('community_browser_execution')!='native'):raise ValueError('自动准备支持已核验本机模式的贴吧、掘金和知乎')
        if a['platform']=='zhihu' and not a.get('automatic_execution'):raise ValueError('请先完成知乎本机发布配置和账号核验')
        destination(a['platform'],data['board'])
        for r in data['replies']:thread_url(a['platform'],r['url'])
        if a['platform'] in ('juejin','csdn'):
            if a['platform']=='csdn':
                from .csdn import validate_payload
                if data['source_boards'] or data['reply_rules']:raise ValueError('CSDN当前请使用已核对原文的指定帖评论，自动查找目标尚未验收')
            else:
                from .juejin import validate_payload
            for label in data['source_boards']:tag_label(label)
            for topic in data['topics']:validate_payload({**topic,'kind':'thread','category':data['board']},data['board'])
            for reply in data['replies']+data['reply_rules']:validate_payload({**reply,'kind':'reply'},data['replies'][0]['url'] if data['replies'] else ('https://blog.csdn.net/fixture_author/article/details/123456789' if a['platform']=='csdn' else 'https://juejin.cn/post/1000000000000000000'))
        elif a['platform']=='zhihu':
            from .zhihu import validate_payload
            if data['reply_rules'] or data['source_boards']:raise ValueError('知乎请使用已核对原文的指定帖评论')
            for topic in data['topics']:
                validate_payload({**topic,'kind':'thread'})
                if not topic['platform_tags']:raise ValueError('知乎文章需配置相关话题')
            for reply in data['replies']:validate_payload({**reply,'kind':'reply'})
        elif any(len(t['title'])>31 for t in data['topics']):raise ValueError('贴吧标题最多31字')
        with self.lock,self.store.connect(True) as db:
            # Account deletion and plan creation share the same write transaction.
            if not db.execute('SELECT 1 FROM community_accounts WHERE id=?',(a['id'],)).fetchone():raise ValueError('账号已删除，请重新选择')
            if ident:
                old=db.execute('SELECT * FROM community_plans WHERE id=?',(ident,)).fetchone()
                if not old:raise ValueError('每日计划不存在')
                if old['state']=='enabled':raise ValueError('请先暂停每日计划再修改')
                if json.loads(old['payload'])['account_id']!=a['id']:raise ValueError('已有计划不能替换账号，请新建计划')
                db.execute("UPDATE community_plans SET payload=?,state='paused',message='配置已保存，待启用',updated=? WHERE id=?",(dumps(data),now,ident))
                if data['replies_per_day']==0:
                    # Closing replies also closes unsent daily/backfill snapshots;
                    # successful and uncertain receipts remain immutable.
                    reply_posts="SELECT post_id FROM community_plan_items WHERE plan_id=? AND kind='reply' UNION SELECT post_id FROM community_backfill WHERE plan_id=? AND kind='reply'"
                    db.execute(f"UPDATE community_jobs SET state='cancelled',message='自动评论已关闭，取消未发送任务',updated=? WHERE state IN ('queued','paused','manual') AND post_id IN ({reply_posts})",(now,ident,ident))
                    db.execute(f"UPDATE community_jobs SET message='cancel_requested' WHERE state='running' AND post_id IN ({reply_posts})",(ident,ident))
                    from .service import SHANGHAI
                    today=datetime.fromtimestamp(now,SHANGHAI).date().isoformat()
                    db.execute('UPDATE community_plan_checks SET reply_goal=0 WHERE plan_id=? AND day=?',(ident,today))
                    db.execute("UPDATE community_plan_days SET message='仅发帖子；自动评论已关闭，已发布记录保留',updated=? WHERE plan_id=? AND day=?",(now,ident,today))
            else:
                ident=uid();db.execute('INSERT INTO community_plans VALUES(?,?,?,?,?,?,?,?,?)',
                    (ident,dumps(data),'paused','',0,'','配置已保存，待启用',now,now))
        return {'id':ident,'message':f"每日计划已保存；每天1篇帖子、评论{data['replies_per_day']}个不同帖子；缺口会定时重查"}

    def control(self,ident,action):
        if action=='continue-today':return self.s.backfill.queue(ident,today_only=True)
        if action=='sync-receipts':return self.sync_receipts(ident)
        if action=='prepare-materials':
            return self.s.materials.request(ident)
        with self.lock:
            p=self.get(ident);now=self.s.clock()
            if action=='enable':
                self.s.check_account(p['payload']['account_id']);a=self.s.account(p['payload']['account_id'])
                with self.store.connect(True) as db:
                    if db.execute("SELECT 1 FROM community_risk WHERE platform=?",(a['platform'],)).fetchone():raise ValueError('此平台存在暂停记录，先核实后再启用每日计划')
                    if db.execute("SELECT 1 FROM community_plans p JOIN community_accounts a ON a.id=json_extract(p.payload,'$.account_id') WHERE p.state='enabled' AND p.id!=? AND json_extract(a.data,'$.platform')=?",(ident,a['platform'])).fetchone():raise ValueError('此平台已有启用的每日计划，请先暂停；每日预算所有账号共享')
                    db.execute("UPDATE community_plans SET state='enabled',identity=?,account_version=?,revision=?,message='每日计划已启用',updated=? WHERE id=?",(a['identity'],a['version'],self.s.cfg.code_revision,now,ident))
                return {'message':'每日计划已启用；暂停过的发送任务不会自动恢复'}
            if action=='pause':
                with self.store.connect(True) as db:
                    db.execute("UPDATE community_plans SET state='paused',message='用户暂停每日计划',updated=? WHERE id=?",(now,ident))
                    db.execute("UPDATE community_jobs SET state='paused',message='每日计划暂停',updated=? WHERE state='queued' AND post_id IN (SELECT post_id FROM community_plan_items WHERE plan_id=?)",(now,ident))
                    db.execute("UPDATE community_jobs SET message='stop_requested' WHERE state='running' AND post_id IN (SELECT post_id FROM community_plan_items WHERE plan_id=?)",(ident,))
                return {'message':'每日计划已暂停，尚未提交的动作已停止'}
            if action=='today':return self.prepare(ident,force=True)
            raise ValueError('未知每日计划操作')

    def sync_receipts(self,ident):
        """Attribute today's existing successful records; never invent a receipt."""
        from .service import SHANGHAI
        with self.lock,self.store.connect(True) as db:
            p=self.get(ident);a=self.s.account(p['payload']['account_id']);now=self.s.clock()
            local=datetime.fromtimestamp(now,SHANGHAI);day=local.date().isoformat()
            midnight=local.replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
            rows=list(db.execute("""SELECT j.post_id,j.snapshot,j.receipt FROM community_jobs j
                WHERE j.account_id=? AND j.platform=?
                  AND (j.identity=? OR (j.state='recorded' AND j.identity=?))
                  AND ((j.state='submitted' AND j.started>=? AND j.started<?)
                   OR (j.state='recorded' AND j.updated>=? AND j.updated<?))""",
                (a['id'],a['platform'],a['identity'],'manual:'+a['id'],midnight,midnight+86400,midnight,midnight+86400)))
            linked=0;attributed=0
            for row in rows:
                receipt=json.loads(row['receipt'])
                if not receipt.get('url'):continue
                snapshot=json.loads(row['snapshot'])
                # Earlier web-only records use an account-scoped manual identity.
                # Preserve that weaker evidence; never attribute a different known identity.
                saved_account=snapshot.get('account',{})
                if saved_account.get('id')!=a['id'] or saved_account.get('identity') not in ('',a['identity']):continue
                payload=snapshot['payload'];kind=payload.get('kind','thread')
                if kind not in ('thread','reply'):continue
                linked+=db.execute('INSERT OR IGNORE INTO community_plan_items VALUES(?,?,?,?,?)',(ident,day,kind,material_id(payload['body']),row['post_id'])).rowcount
                if db.execute('SELECT 1 FROM community_plan_items WHERE plan_id=? AND post_id=?',(ident,row['post_id'])).fetchone():attributed+=1
            if attributed:
                db.execute("INSERT INTO community_plan_days VALUES(?,?,'planned','按当天实际发布回执统计；原计划日期保留在内容详情',?,?) ON CONFLICT(plan_id,day) DO UPDATE SET message=excluded.message,updated=excluded.updated",(ident,day,now,now))
            return {'message':f'已将 {linked} 条当天真实回执关联到计划；没有新建或重复发布内容','linked':linked}

    def tick(self):
        from .service import SHANGHAI
        today=datetime.fromtimestamp(self.s.clock(),SHANGHAI).date().isoformat()
        # An evening test may legitimately finish after midnight. Expire its
        # unsent queue at the next daily start, not in the middle of its spacing.
        with self.store.connect(True) as db:
            for row in db.execute("SELECT DISTINCT i.plan_id,i.day,p.payload FROM community_plan_items i JOIN community_plans p ON p.id=i.plan_id WHERE i.day<?",(today,)).fetchall():
                payload=json.loads(row['payload'])
                deadline=datetime.fromisoformat(row['day']).replace(tzinfo=SHANGHAI)+timedelta(days=1,hours=payload['hour'],minutes=payload['minute'])
                if self.s.clock()>=deadline.timestamp():
                    db.execute("""UPDATE community_jobs SET state='cancelled',message='已到下一日计划时间，不积压补发' WHERE state='queued'
                      AND post_id IN (SELECT post_id FROM community_plan_items WHERE plan_id=? AND day=?)
                      AND post_id NOT IN (SELECT post_id FROM community_backfill WHERE post_id!='')""",(row['plan_id'],row['day']))
        for p in self.store.rows("SELECT id FROM community_plans WHERE state='enabled'"):
            self.prepare(p['id'])

    def recover(self):
        if hasattr(self.s,'materials'):self.s.materials.recover()
        with self.store.connect(True) as db:
            for r in list(db.execute("SELECT plan_id FROM community_plan_days WHERE state='preparing'")):
                db.execute("UPDATE community_plan_checks SET next_check=? WHERE plan_id=?",(self.s.clock(),r['plan_id']))
            # Atomic post + job + item commits are safe to count and supplement.
            # Community.recover separately locks any running/unknown write.
            db.execute("UPDATE community_plan_days SET state='waiting',message='准备中断，恢复后核对原记录并补充缺口' WHERE state='preparing'")

    def prepare(self,ident,force=False):
        from .service import SHANGHAI
        with self.lock:
            p=self.get(ident);now=self.s.clock();local=datetime.fromtimestamp(now,SHANGHAI);day=local.date().isoformat()
            if p['state']!='enabled':
                if force:raise ValueError('请先启用每日计划')
                return {'message':'每日计划未启用'}
            d=p['payload'];due=local.replace(hour=d['hour'],minute=d['minute'],second=0,microsecond=0).timestamp()
            if d.get('start_date') and day<d['start_date']:
                return {'message':'等待计划开始日期 '+d['start_date']}
            if not force and now<due:return {'message':'等待每日执行时间'}
            self.sync_receipts(ident)
            checks=self.store.rows('SELECT * FROM community_plan_checks WHERE plan_id=? AND day=?',(ident,day))
            if checks and not force and (not checks[0]['next_check'] or now<checks[0]['next_check']):
                return {'message':'等待下次检查；已有任务保持原记录'}
            a=self.s.account(d['account_id'])
            reason=''
            if a.get('automatic_execution') is False:reason='当前使用网页发布，每日自动发布已停用，内容和历史记录保留'
            if not a['enabled'] or a['version']!=p['account_version'] or a['identity']!=p['identity'] or p['revision']!=self.s.cfg.code_revision:
                reason='账号或代码版本改变，请检查计划后重新启用'
            if self.store.rows('SELECT 1 FROM community_risk WHERE platform=?',(a['platform'],)):reason='此平台有暂停记录，本日停止发送'
            if reason:
                with self.store.connect(True) as db:db.execute("UPDATE community_plans SET state='paused',message=?,updated=? WHERE id=?",(reason,now,ident))
                return {'message':reason}
            pending=self.store.rows("""SELECT COUNT(*) AS n FROM community_backfill b
                JOIN community_jobs j ON j.post_id=b.post_id
                WHERE b.plan_id=? AND j.state IN ('queued','running')""",(ident,))[0]['n']
            if pending:
                message=f'优先执行历史补发 {pending} 项；与今天共用每日额度，暂不新增普通队列'
                with self.store.connect(True) as db:
                    db.execute("INSERT INTO community_plan_days VALUES(?,?,'waiting',?,?,?) ON CONFLICT(plan_id,day) DO UPDATE SET state='waiting',message=excluded.message,updated=excluded.updated",(ident,day,message,now,now))
                    db.execute('INSERT INTO community_plan_checks VALUES(?,?,?,0,?) ON CONFLICT(plan_id,day) DO UPDATE SET next_check=excluded.next_check',(ident,day,now+1800,d.get('replies_per_day',5)))
                    db.execute('UPDATE community_plans SET message=?,updated=? WHERE id=?',(message,now,ident))
                return {'message':message}
            with self.store.connect(True) as db:
                db.execute("INSERT INTO community_plan_days VALUES(?,?,'preparing','正在筛选素材与目标',?,?) ON CONFLICT(plan_id,day) DO UPDATE SET state='preparing',updated=excluded.updated",(ident,day,now,now))
                db.execute('INSERT OR IGNORE INTO community_plan_checks VALUES(?,?,0,0,?)',(ident,day,d.get('replies_per_day',5)))
            try:
                # Recheck live identity before materializing any write jobs.
                if hasattr(self.s.adapter,'ensure_connection'):self.s.adapter.ensure_connection(self.s.account(a['id'],True))
                self.s.check_account(a['id'])
                used={r['material'] for r in self.store.rows('SELECT material FROM community_plan_items WHERE plan_id=?',(ident,))}
                used.update(material_id(json.loads(r['payload'])['body']) for r in self.store.rows('SELECT p.payload FROM community_backfill b JOIN community_posts p ON p.id=b.post_id WHERE b.plan_id=?',(ident,)))
                targets={r['value'] for r in self.store.rows("SELECT value FROM community_claims WHERE platform=? AND identity=? AND scope='reply_target'",(a['platform'],a['identity']))}
                existing=self.day_jobs(p,day)
                created={k:sum(r['kind']==k for r in existing) for k in ('thread','reply')}
                errors=[]
                reply_goal=d.get('replies_per_day',5)
                # A changed setting affects only missing work; existing snapshots remain fixed.
                with self.store.connect(True) as db:db.execute('UPDATE community_plan_checks SET reply_goal=? WHERE plan_id=? AND day=?',(reply_goal,ident,day))
                available=self.s.materials.available(p,day) if d.get('auto_prepare') else {'thread':d['topics'],'reply':d['replies']}
                topics=[t for t in available['thread'] if material_id(t['body']) not in used]
                midnight=local.replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
                today=self.store.rows("SELECT snapshot FROM community_jobs WHERE platform=? AND (started>=? OR (state='recorded' AND updated>=?))",(a['platform'],midnight,midnight))
                thread_used=any(json.loads(r['snapshot'])['payload'].get('kind','thread')=='thread' for r in today)
                def enqueue(kind,material,target):
                    key=material_id(material['body'])
                    request='daily-'+hashlib.sha256((ident+day+key).encode()).hexdigest()[:40]
                    payload=CommunityPost(request_id=request,kind=kind,title=material['title'][:(31 if a['platform']=='tieba' else 100)] if kind=='thread' else '回复：'+material['title'][:27],
                        body=material['body'],source_title=material.get('title','') if kind=='reply' else '',source_excerpt=material.get('excerpt',''),
                        category=d['board'] if a['platform']=='juejin' and kind=='thread' else '',
                        platform_tags=material.get('platform_tags',[]) if kind=='thread' else (material.get('source_tags') or material.get('tags',[]))[:3],
                        targets=[{'account_id':a['id'],'destination':target}])
                    try:
                        with self.store.connect(True) as db:
                            current=db.execute('SELECT state FROM community_plans WHERE id=?',(ident,)).fetchone()
                            if current['state']!='enabled':return
                            post=self.s.save(payload,_db=db)['id']
                            self.s.launch(post,_db=db)
                            db.execute('INSERT INTO community_plan_items VALUES(?,?,?,?,?)',(ident,day,kind,key,post))
                    except ValueError as ex:
                        errors.append(str(ex));return
                    created[kind]+=1
                # Article preparation is independent of reply discovery.
                if topics and not thread_used and not created['thread']:enqueue('thread',topics[0],d['board'])
                needed=max(0,reply_goal-created['reply'])
                replies=[]
                from .registry import reply_target_key
                for r in available['reply']:
                    if len(replies)>=needed:break
                    key=material_id(r['body'])
                    target_key=reply_target_key(a['platform'],r['url'])
                    if key in used or target_key in targets:continue
                    replies.append(r);used.add(key);targets.add(target_key)
                discover_note=''
                rules=[r for r in d['reply_rules'] if material_id(r['body']) not in used]
                if len(replies)<needed and rules and d['source_boards']:
                    try:candidates=self.s.adapter.discover(self.s.account(a['id'],True),d['source_boards'])
                    except Exception:candidates=[];discover_note='本次读取候选未完成；没有用无关帖子补足'
                    for c in candidates:
                        try:url=thread_url(a['platform'],c['url'])
                        except (ValueError,KeyError):
                            discover_note='已丢弃目标平台不一致或地址无效的候选';continue
                        if url in targets or c.get('author_id')==a['identity']:continue
                        r=next((r for r in rules if material_id(r['body']) not in used and eligible(r,c)),None)
                        if not r:continue
                        replies.append({**c,'url':url,'body':r['body'],'keyword':r['name']})
                        used.add(material_id(r['body']));targets.add(url)
                        if len(replies)>=needed:break
                for r in replies:enqueue('reply',r,r['url'])
                message=(f"已安排帖子 {created['thread']}/1、评论 {created['reply']}/{reply_goal}；同帖和内容不重复" if reply_goal else f"已安排帖子 {created['thread']}/1；自动评论已关闭，已发布记录保留")
                if created['thread']<1:message+='；今日文章额度已用（含网页登记）' if thread_used else '；主题素材不足'
                if created['reply']<reply_goal:message+='；合适目标或未用评论素材不足'
                if discover_note:message+='；'+discover_note
                if errors:message+='；'+errors[0]
                with self.store.connect(True) as db:
                    shortage=(created['thread']<1 and not thread_used) or created['reply']<reply_goal
                    next_check=self.s.clock()+1800 if shortage else 0
                    if shortage:message+='；30分钟后自动重查'
                    db.execute('UPDATE community_plan_checks SET next_check=?,attempts=0 WHERE plan_id=? AND day=?',(next_check,ident,day))
                    db.execute("UPDATE community_plan_days SET state='planned',message=?,updated=? WHERE plan_id=? AND day=?",(message,self.s.clock(),ident,day))
                    db.execute("UPDATE community_plans SET message=?,updated=? WHERE id=? AND state='enabled'",(message,self.s.clock(),ident))
                return {'message':message}
            except IdentityChanged as ex:
                message=str(ex)
                with self.store.connect(True) as db:
                    db.execute("UPDATE community_plan_days SET state='error',message=?,updated=? WHERE plan_id=? AND day=?",(message,self.s.clock(),ident,day))
                    db.execute("UPDATE community_plans SET state='paused',message=?,updated=? WHERE id=?",(message,self.s.clock(),ident))
                    db.execute("UPDATE community_jobs SET state='paused',message=? WHERE state='queued' AND post_id IN (SELECT post_id FROM community_plan_items WHERE plan_id=?)",(message,ident))
                return {'message':message}
            except Exception:
                attempts=(checks[0]['attempts'] if checks else 0)+1
                delay=min(1800,300*2**min(attempts-1,3))
                message=f'准备检查暂未完成，{delay//60}分钟后自动重查；请确认原账号Chrome登录状态'
                with self.store.connect(True) as db:
                    db.execute('UPDATE community_plan_checks SET next_check=?,attempts=? WHERE plan_id=? AND day=?',(self.s.clock()+delay,attempts,ident,day))
                    db.execute("UPDATE community_plan_days SET state='waiting',message=?,updated=? WHERE plan_id=? AND day=?",(message,self.s.clock(),ident,day))
                    db.execute("UPDATE community_plans SET message=?,updated=? WHERE id=? AND state='enabled'",(message,self.s.clock(),ident))
                return {'message':message}
