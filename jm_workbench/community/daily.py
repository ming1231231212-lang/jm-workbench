"""Durable daily planning. A shortage is recorded, never filled with unrelated replies."""
import hashlib
import json
import threading
from datetime import datetime, timedelta
from .models import CommunityPost
from .registry import tieba_thread_url
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
    return not rule['require_question'] or bool(re.search(r'怎么|如何|哪里|哪个|求助|求推荐|有没有|请教|[?？]',text))


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
            ''')

    def get(self,ident):
        rows=self.store.rows('SELECT * FROM community_plans WHERE id=?',(ident,))
        if not rows:raise ValueError('每日计划不存在')
        r=rows[0];r['payload']=json.loads(r['payload']);return r

    def state(self):
        plans=[]
        for row in self.store.rows('SELECT id FROM community_plans ORDER BY created DESC'):
            p=self.get(row['id']);items=self.store.rows('SELECT * FROM community_plan_items WHERE plan_id=?',(p['id'],))
            used={i['material'] for i in items}
            p['remaining_topics']=sum(material_id(t['body']) not in used for t in p['payload']['topics'])
            p['remaining_replies']=sum(material_id(t['body']) not in used for t in p['payload']['replies']+p['payload']['reply_rules'])
            days=self.store.rows('SELECT * FROM community_plan_days WHERE plan_id=? ORDER BY day DESC LIMIT 14',(p['id'],))
            for d in days:
                jobs=self.store.rows('''SELECT i.kind,j.state FROM community_plan_items i JOIN community_jobs j ON j.post_id=i.post_id
                    WHERE i.plan_id=? AND i.day=?''',(p['id'],d['day']))
                d['counts']={k:{'planned':sum(j['kind']==k for j in jobs),'submitted':sum(j['kind']==k and j['state']=='submitted' for j in jobs),
                   'waiting':sum(j['kind']==k and j['state'] in ('queued','paused') for j in jobs),'failed':sum(j['kind']==k and j['state'] in ('failed','unknown') for j in jobs)} for k in ('thread','reply')}
            p['days']=days;plans.append(p)
        return plans

    def save(self,payload,ident=None):
        data=payload.model_dump();now=self.s.clock()
        a=self.s.account(data['account_id'])
        if a['platform']!='tieba':raise ValueError('每日评论计划仅支持百度贴吧')
        with self.lock,self.store.connect(True) as db:
            # Account deletion and plan creation share the same write transaction.
            if not db.execute('SELECT 1 FROM community_accounts WHERE id=?',(a['id'],)).fetchone():raise ValueError('账号已删除，请重新选择')
            if ident:
                old=db.execute('SELECT * FROM community_plans WHERE id=?',(ident,)).fetchone()
                if not old:raise ValueError('每日计划不存在')
                if old['state']=='enabled':raise ValueError('请先暂停每日计划再修改')
                if json.loads(old['payload'])['account_id']!=a['id']:raise ValueError('已有计划不能替换账号，请新建计划')
                db.execute("UPDATE community_plans SET payload=?,state='paused',message='配置已保存，待启用',updated=? WHERE id=?",(dumps(data),now,ident))
            else:
                ident=uid();db.execute('INSERT INTO community_plans VALUES(?,?,?,?,?,?,?,?,?)',
                    (ident,dumps(data),'paused','',0,'','配置已保存，待启用',now,now))
        return {'id':ident,'message':'每日计划已保存；每天1篇帖子、评论5个不同帖子，素材与目标不足时记录缺口'}

    def control(self,ident,action):
        with self.lock:
            p=self.get(ident);now=self.s.clock()
            if action=='enable':
                self.s.check_account(p['payload']['account_id']);a=self.s.account(p['payload']['account_id'])
                with self.store.connect(True) as db:
                    if db.execute("SELECT 1 FROM community_risk WHERE platform='tieba'").fetchone():raise ValueError('贴吧存在暂停记录，先核实后再启用每日计划')
                    if db.execute("SELECT 1 FROM community_plans WHERE state='enabled' AND id!=?",(ident,)).fetchone():raise ValueError('贴吧已有启用的每日计划，请先暂停；每日预算所有账号共享')
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

    def tick(self):
        from .service import SHANGHAI
        today=datetime.fromtimestamp(self.s.clock(),SHANGHAI).date().isoformat()
        # Do not catch up yesterday's work after shutdown or quota delays.
        with self.store.connect(True) as db:
            db.execute("""UPDATE community_jobs SET state='cancelled',message='已过计划日期，不追补发送' WHERE state='queued'
              AND post_id IN (SELECT post_id FROM community_plan_items WHERE day<?)""",(today,))
        for p in self.store.rows("SELECT id FROM community_plans WHERE state='enabled'"):
            self.prepare(p['id'])

    def recover(self):
        with self.store.connect(True) as db:
            for r in list(db.execute("SELECT plan_id FROM community_plan_days WHERE state='preparing'")):
                db.execute("UPDATE community_plans SET state='paused',message='服务在准备阶段中断，请核对已创建记录' WHERE id=?",(r['plan_id'],))
                db.execute("UPDATE community_jobs SET state='paused',message='准备阶段中断，保留任务待核对' WHERE state='queued' AND post_id IN (SELECT post_id FROM community_plan_items WHERE plan_id=?)",(r['plan_id'],))
            db.execute("UPDATE community_plan_days SET state='error',message='服务在准备阶段中断，不自动重建' WHERE state='preparing'")

    def prepare(self,ident,force=False):
        from .service import SHANGHAI
        with self.lock:
            p=self.get(ident);now=self.s.clock();local=datetime.fromtimestamp(now,SHANGHAI);day=local.date().isoformat()
            if p['state']!='enabled':
                if force:raise ValueError('请先启用每日计划')
                return {'message':'每日计划未启用'}
            d=p['payload'];due=local.replace(hour=d['hour'],minute=d['minute'],second=0,microsecond=0).timestamp()
            if not force and now<due:return {'message':'等待每日执行时间'}
            if self.store.rows('SELECT 1 FROM community_plan_days WHERE plan_id=? AND day=?',(ident,day)):
                return {'message':'今天已经安排过，不会重复创建或发送'}
            a=self.s.account(d['account_id'])
            reason=''
            if not a['enabled'] or a['version']!=p['account_version'] or a['identity']!=p['identity'] or p['revision']!=self.s.cfg.code_revision:
                reason='账号或代码版本改变，请检查计划后重新启用'
            if self.store.rows("SELECT 1 FROM community_risk WHERE platform='tieba'"):reason='贴吧有暂停记录，本日停止发送'
            if reason:
                with self.store.connect(True) as db:db.execute("UPDATE community_plans SET state='paused',message=?,updated=? WHERE id=?",(reason,now,ident))
                return {'message':reason}
            with self.store.connect(True) as db:
                db.execute("INSERT INTO community_plan_days VALUES(?,?,'preparing','正在筛选素材与目标',?,?)",(ident,day,now,now))
            try:
                # Recheck live identity before materializing any write jobs.
                self.s.check_account(a['id'])
                used={r['material'] for r in self.store.rows('SELECT material FROM community_plan_items WHERE plan_id=?',(ident,))}
                targets={r['value'] for r in self.store.rows("SELECT value FROM community_claims WHERE platform='tieba' AND identity=? AND scope='reply_target'",(a['identity'],))}
                prepared=[]
                topics=[t for t in d['topics'] if material_id(t['body']) not in used]
                if topics:prepared.append(('thread',topics[0],d['board']))
                replies=[]
                for r in d['replies']:
                    key=material_id(r['body'])
                    if key in used or r['url'] in targets:continue
                    replies.append(r);used.add(key);targets.add(r['url'])
                    if len(replies)>=5:break
                discover_note=''
                rules=[r for r in d['reply_rules'] if material_id(r['body']) not in used]
                if len(replies)<5 and rules and d['source_boards']:
                    try:candidates=self.s.adapter.discover(self.s.account(a['id'],True),d['source_boards'])
                    except Exception:candidates=[];discover_note='本次读取候选未完成；没有用无关帖子补足'
                    for c in candidates:
                        url=tieba_thread_url(c['url'])
                        if url in targets or c.get('author_id')==a['identity']:continue
                        r=next((r for r in rules if material_id(r['body']) not in used and eligible(r,c)),None)
                        if not r:continue
                        replies.append({**c,'url':url,'body':r['body'],'keyword':r['name']})
                        used.add(material_id(r['body']));targets.add(url)
                        if len(replies)>=5:break
                prepared.extend(('reply',r,r['url']) for r in replies)
                created={'thread':0,'reply':0};errors=[]
                for kind,material,target in prepared:
                    key=material_id(material['body'])
                    request='daily-'+hashlib.sha256((ident+day+key).encode()).hexdigest()[:40]
                    payload=CommunityPost(request_id=request,kind=kind,title=material['title'][:31] if kind=='thread' else '回复：'+material['title'][:27],
                        body=material['body'],source_title=material.get('title','') if kind=='reply' else '',source_excerpt=material.get('excerpt',''),
                        targets=[{'account_id':a['id'],'destination':target}])
                    # Each post+job+plan association is protected by the planner lock;
                    # worker cannot send until prepare returns (Community.step_lock).
                    try:
                        with self.store.connect(True) as db:
                            post=self.s.save(payload,_db=db)['id']
                            self.s.launch(post,_db=db)
                            db.execute('INSERT INTO community_plan_items VALUES(?,?,?,?,?)',(ident,day,kind,key,post))
                    except ValueError as ex:
                        errors.append(str(ex));continue
                    created[kind]+=1
                message=f"已安排帖子 {created['thread']}/1、评论 {created['reply']}/5；同帖和内容不重复"
                if created['thread']<1:message+='；主题素材不足'
                if created['reply']<5:message+='；合适目标或未用评论素材不足'
                if discover_note:message+='；'+discover_note
                if errors:message+='；'+errors[0]
                with self.store.connect(True) as db:
                    db.execute("UPDATE community_plan_days SET state='planned',message=?,updated=? WHERE plan_id=? AND day=?",(message,self.s.clock(),ident,day))
                    db.execute('UPDATE community_plans SET message=?,updated=? WHERE id=?',(message,self.s.clock(),ident))
                return {'message':message}
            except Exception:
                message='每日准备未完成，已暂停计划；保留已创建记录，不自动重建或重发'
                with self.store.connect(True) as db:
                    db.execute("UPDATE community_plan_days SET state='error',message=?,updated=? WHERE plan_id=? AND day=?",(message,self.s.clock(),ident,day))
                    db.execute("UPDATE community_plans SET state='paused',message=?,updated=? WHERE id=?",(message,self.s.clock(),ident))
                    db.execute("UPDATE community_jobs SET state='paused',message=? WHERE state='queued' AND post_id IN (SELECT post_id FROM community_plan_items WHERE plan_id=?)",(message,ident))
                return {'message':message}
