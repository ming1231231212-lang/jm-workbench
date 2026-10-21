"""Durable replenishment. Preparation never enqueues or submits a publication."""
import hashlib
import json
import threading
from datetime import datetime,timedelta
from .daily import material_id
from .material_model import MaterialModel
from .material_quality import rank_candidates,validate_generated
from .registry import thread_url
from ..core.db import dumps,uid

BRIEF='趣造AI，网址quzaoai.com，由本人维护，希望大家一起使用并补充具体使用反馈，把网站逐步做成大家共同参与的网站。没有核验的具体功能、价格、效果、人数不能声称已支持或已达到。'

def validate_batch(raw,platform,candidates,history,targets,need_article):
    """Keep independently valid items, so one poor comment cannot waste a day."""
    result={'article':None,'replies':[]};issues=[];bodies=list(history);used=set(targets)
    if not isinstance(raw,dict):raise ValueError('模型结果格式不正确')
    if need_article:
        try:
            result['article']=validate_generated({'article':raw.get('article'),'replies':[]},platform,candidates,bodies,used,True)['article']
            bodies.append(result['article']['body'])
        except ValueError as ex:issues.append(str(ex))
    replies=raw.get('replies',[])
    if not isinstance(replies,list) or len(replies)>5:raise ValueError('评论格式或数量不正确')
    for row in replies:
        try:
            accepted=validate_generated({'article':None,'replies':[row]},platform,candidates,bodies,used,False)['replies'][0]
            result['replies'].append(accepted);bodies.append(accepted['body']);used.add(accepted['url'])
        except (ValueError,TypeError,KeyError,IndexError):issues.append('一条评论未通过原文、相关性或重复检查')
    if not result['article'] and not result['replies']:raise ValueError(issues[0] if issues else '没有通过检查的内容')
    return result,issues

class AutoMaterials:
    def __init__(self,community,model=None):
        self.s=community;self.store=community.store;self.model=model or MaterialModel(community.cfg.config)
        self.lock=threading.Lock()
        with self.store.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS community_preparations(plan_id TEXT,day TEXT,state TEXT,message TEXT,
              attempts INTEGER,next_check REAL,fingerprint TEXT,data TEXT,created REAL,updated REAL,PRIMARY KEY(plan_id,day));
            CREATE TABLE IF NOT EXISTS community_materials(id TEXT PRIMARY KEY,plan_id TEXT,day TEXT,kind TEXT,
              payload TEXT,fingerprint TEXT,created REAL,UNIQUE(plan_id,day,kind,payload));
            ''')
        if isinstance(self.model,MaterialModel):
            configured=self.model.config.values.get('community_model_name','nvidia/nemotron-3-super-120b-a12b:free')
            for row in self.store.rows("SELECT data FROM community_preparations WHERE state='ready' ORDER BY updated DESC LIMIT 30"):
                data=json.loads(row['data']);source=data.get('generation_model',{})
                model=source.get('model','')
                if data.get('review') and isinstance(model,str) and model.endswith(':free') and source.get('configured_model','nvidia/nemotron-3-super-120b-a12b:free')==configured:
                    self.model.prefer_free_model(model);break
    def fingerprint(self,p):
        return hashlib.sha256(dumps([p['payload'],p['identity'],p['account_version'],p['revision']]).encode()).hexdigest()
    def active(self,p):
        a=self.s.account(p['payload']['account_id'])
        return p['state']=='enabled' and p['payload'].get('auto_prepare') and a['enabled'] and a.get('automatic_execution') is not False and a['version']==p['account_version'] and a['identity']==p['identity'] and p['revision']==self.s.cfg.code_revision and not self.store.rows('SELECT 1 FROM community_risk WHERE platform=?',(a['platform'],))
    def state(self,ident):
        rows=self.store.rows('SELECT * FROM community_preparations WHERE plan_id=? ORDER BY day DESC LIMIT 7',(ident,))
        for r in rows:r['data']=json.loads(r['data'])
        return rows
    def pool(self,p,day):
        rows=self.store.rows('SELECT kind,payload FROM community_materials WHERE plan_id=? AND day=? AND fingerprint=? ORDER BY created,id',(p['id'],day,self.fingerprint(p)))
        return {k:[json.loads(r['payload']) for r in rows if r['kind']==k] for k in ('thread','reply')}
    def history(self,a):
        from .service import reply_target_key
        bodies=[];targets=set()
        for r in self.store.rows('SELECT payload FROM community_posts'):
            d=json.loads(r['payload'])
            # Same public voice: generated content may not duplicate other platforms either.
            bodies.append(d['body'])
            if d.get('kind')=='reply':
                for target in d['targets']:
                    try:
                        other=self.s.account(target['account_id'])
                        if other['platform']==a['platform']:targets.add(thread_url(a['platform'],target['destination']))
                    except ValueError:pass
        for r in self.store.rows('SELECT payload,kind FROM community_materials'):
            d=json.loads(r['payload']);bodies.append(d['body'])
            if r['kind']=='reply':
                try:targets.add(thread_url(a['platform'],d['url']))
                except ValueError:pass
        claims={r['value'] for r in self.store.rows("SELECT value FROM community_claims WHERE platform=? AND identity=? AND scope='reply_target'",(a['platform'],a['identity']))}
        return bodies,targets,claims
    def available(self,p,day):
        from .service import reply_target_key
        a=self.s.account(p['payload']['account_id']);pool=self.pool(p,day)
        used={r['material'] for r in self.store.rows('SELECT material FROM community_plan_items WHERE plan_id=?',(p['id'],))}
        claimed={r['value'] for r in self.store.rows("SELECT value FROM community_claims WHERE platform=? AND identity=? AND scope='reply_target'",(a['platform'],a['identity']))}
        used_bodies={r['value'] for r in self.store.rows("SELECT value FROM community_claims WHERE platform=? AND identity=? AND scope='content'",(a['platform'],a['identity']))}
        used|=used_bodies;result={'thread':[],'reply':[]};seen=set()
        for kind,key in [('thread','topics'),('reply','replies')]:
            for d in p['payload'][key]+pool[kind]:
                body=material_id(d['body'])
                if body in used:continue
                if kind=='reply':
                    target=reply_target_key(a['platform'],d['url'])
                    if target in claimed or target in seen:continue
                    seen.add(target)
                result[kind].append(d);used.add(body)
        return result
    def tick(self):
        from .service import SHANGHAI
        now=self.s.clock();local=datetime.fromtimestamp(now,SHANGHAI)
        for row in self.store.rows("SELECT plan_id,day FROM community_preparations WHERE state='requested' ORDER BY updated"):
            p=self.s.daily.get(row['plan_id'])
            if self.active(p) and row['day']>=local.date().isoformat():
                self.prepare(row['plan_id'],row['day']);return
        for row in self.store.rows("SELECT id FROM community_plans WHERE state='enabled'"):
            p=self.s.daily.get(row['id']);d=p['payload']
            if not d.get('auto_prepare'):continue
            due=local.replace(hour=d['hour'],minute=d['minute'],second=0,microsecond=0)
            day=local.date().isoformat()
            if d.get('start_date') and day<d['start_date']:continue
            if now<(due-timedelta(hours=1)).timestamp():continue
            if self.prepare(p['id'],day).get('worked'):return # At most one bounded supply pass per tick.
        # Keep one day of posts in reserve; this never creates publication jobs.
        # Current-day shortages take priority over tomorrow's inventory.
        for row in self.store.rows("SELECT id FROM community_plans WHERE state='enabled'"):
            p=self.s.daily.get(row['id']);d=p['payload'];day=local.date().isoformat()
            if not self.active(p) or d.get('replies_per_day',5):continue
            ready=next((r for r in self.state(p['id']) if r['day']==day and r['fingerprint']==self.fingerprint(p)),None)
            if not ready or ready['state']!='ready':continue
            tomorrow=(local.date()+timedelta(days=1)).isoformat()
            if self.prepare(p['id'],tomorrow).get('worked'):return
    def request(self,ident):
        from .service import SHANGHAI
        p=self.s.daily.get(ident);now=self.s.clock();today=datetime.fromtimestamp(now,SHANGHAI).date()
        if not self.active(p):raise ValueError('先启用自动准备和计划，再检查素材')
        day=max(today.isoformat(),p['payload'].get('start_date') or today.isoformat())
        if day>(today+timedelta(days=1)).isoformat():raise ValueError('开始日期较远，将在当天提前一小时准备')
        with self.store.connect(True) as db:
            db.execute("INSERT INTO community_preparations VALUES(?,?,'requested','已安排后台检查素材缺口',0,?,?,?, ?,?) ON CONFLICT(plan_id,day) DO UPDATE SET state='requested',message=excluded.message,next_check=excluded.next_check,updated=excluded.updated",(ident,day,now,self.fingerprint(p),dumps({'counts':{},'sources':[],'review':''}),now,now))
        return {'message':'已安排后台检查素材缺口；准备过程和正文会在计划里更新，不会提前发布'}
    def recover(self):
        with self.store.connect(True) as db:
            db.execute("UPDATE community_preparations SET state='waiting',message='准备中断，保留已有素材，稍后重新核对',next_check=? WHERE state='preparing'",(self.s.clock()+300,))
    def prepare(self,ident,day,force=False):
        if not self.lock.acquire(blocking=False):return {'message':'其他素材正在准备'}
        try:return self._prepare(ident,day,force)
        finally:self.lock.release()
    def _prepare(self,ident,day,force):
        from .service import reply_target_key,SHANGHAI
        p=self.s.daily.get(ident);now=self.s.clock()
        if not self.active(p):return {'message':'计划暂停或配置变化，未准备'}
        # Explicit preparation supports only today/tomorrow and never moves publication dates.
        local=datetime.fromtimestamp(now,SHANGHAI).date();target=datetime.fromisoformat(day).date()
        if target<local or target>local+timedelta(days=1):raise ValueError('只可准备今天或明天的素材')
        if p['payload'].get('start_date') and day<p['payload']['start_date']:return {'message':'等待计划开始日期'}
        fp=self.fingerprint(p);old=self.store.rows('SELECT * FROM community_preparations WHERE plan_id=? AND day=?',(ident,day))
        previous=old[0] if old else None
        if previous and previous['fingerprint']==fp and not force and (previous['state']=='ready' or now<previous['next_check']):return {'message':previous['message']}
        a=self.s.account(p['payload']['account_id']);available=self.available(p,day)
        existing=self.store.rows('SELECT kind FROM community_plan_items WHERE plan_id=? AND day=?',(ident,day))
        missing={k:max(0,goal-sum(i['kind']==k for i in existing)-len(available[k])) for k,goal in [('thread',1),('reply',p['payload'].get('replies_per_day',5))]}
        attempts=(previous['attempts'] if previous and previous['fingerprint']==fp else 0)
        old_data=json.loads(previous['data']) if previous else {}
        data={'counts':{k:len(available[k])+sum(i['kind']==k for i in existing) for k in missing},'sources':[],'review':'',
              'attempt_history':old_data.get('attempt_history',[])[-29:]}
        message='已有素材满足当天1篇文章和评论目标' if p['payload'].get('replies_per_day',5) else '当天1篇文章素材已就绪；自动评论已关闭';state='ready';next_check=0
        if any(missing.values()):
            attempts+=1
            with self.store.connect(True) as db:
                db.execute("INSERT INTO community_preparations VALUES(?,?,'preparing','正在读取相关活跃原帖并准备原创内容',?,?,?,?,?,?) ON CONFLICT(plan_id,day) DO UPDATE SET state='preparing',message=excluded.message,attempts=excluded.attempts,next_check=excluded.next_check,fingerprint=excluded.fingerprint,updated=excluded.updated",(ident,day,attempts,now+1800,fp,dumps(data),now,now))
            stage='sources'
            try:
                bodies,targets,claims=self.history(a)
                # Include manual inventory so generated replies cannot preempt tomorrow's drafts.
                for row in self.store.rows('SELECT payload FROM community_plans'):
                    other=json.loads(row['payload']);bodies.extend(t['body'] for t in other['topics']+other['replies'])
                    if self.s.account(other['account_id'])['platform']==a['platform']:targets.update(r['url'] for r in other['replies'])
                candidates=[]
                terms=p['payload'].get('search_terms') or ['AI工具','AI工作流','AI编程']
                if missing['reply']:
                    account=self.s.account(a['id'],True)
                    account.update(_discovery_exclude=list(targets),_discovery_round=attempts-1,_discovery_boards=p['payload'].get('source_boards') or ['ai工具','chatgpt','人工智能'])
                    try:candidates=rank_candidates(self.s.adapter.discover(account,terms),terms,self.s.clock())
                    except Exception:data['discovery_note']='原帖读取暂未完成；文章继续独立准备，评论稍后重查'
                    candidates=[c for c in candidates if c['url'] not in targets and reply_target_key(a['platform'],c['url']) not in claims and c.get('author_id')!=a['identity']][:7]
                data['sources']=candidates
                if not self.active(self.s.daily.get(ident)) or self.fingerprint(self.s.daily.get(ident))!=fp:return {'message':'准备期间计划已变更，未保存或发送','worked':True}
                if missing['thread'] or candidates:
                    self.model.feedback=(data['attempt_history'][-1]['message'] if data['attempt_history'] else previous['message'] if previous and previous['state']=='waiting' else '')
                    self.model.attempt_index=attempts-1;stage='generate'
                    raw=self.model.generate(a['platform'],day,candidates,bodies,bool(missing['thread']),missing['reply'],BRIEF)
                    data['generation_model']=getattr(self.model,'last_call',{});stage='validate'
                    article=raw.get('article') if isinstance(raw,dict) else None
                    data['candidate_shape']={'article_type':type(article).__name__,
                        'title_length':len(str(article.get('title',''))) if isinstance(article,dict) else 0,
                        'body_length':len(str(article.get('body',''))) if isinstance(article,dict) else 0}
                    prepared,issues=validate_batch(raw,a['platform'],candidates,bodies,targets,bool(missing['thread']))
                    data['quality_notes']=issues
                    prepared['replies']=prepared['replies'][:missing['reply']]
                    stage='review';data['review']=self.model.review(a['platform'],prepared,candidates)
                    data['review_model']=getattr(self.model,'last_call',{});stage='store'
                    current=self.s.daily.get(ident)
                    if not self.active(current) or self.fingerprint(current)!=fp:return {'message':'准备期间计划已变更，未保存或发送','worked':True}
                    with self.s.daily.lock,self.store.connect(True) as db:
                        locked=dict(db.execute('SELECT * FROM community_plans WHERE id=?',(ident,)).fetchone());locked['payload']=json.loads(locked['payload'])
                        if locked['state']!='enabled' or self.fingerprint(locked)!=fp:return {'message':'计划变更，未保存','worked':True}
                        current_account=db.execute('SELECT version,identity,data FROM community_accounts WHERE id=?',(a['id'],)).fetchone()
                        if not current_account or current_account['version']!=p['account_version'] or current_account['identity']!=p['identity'] or not json.loads(current_account['data'])['enabled'] or db.execute('SELECT 1 FROM community_risk WHERE platform=?',(a['platform'],)).fetchone():return {'message':'账号或平台状态变化，未保存','worked':True}
                        for kind,values in [('thread',[prepared['article']] if prepared['article'] else []),('reply',prepared['replies'])]:
                            for value in values:db.execute('INSERT OR IGNORE INTO community_materials VALUES(?,?,?,?,?,?,?)',(uid(),ident,day,kind,dumps(value),fp,self.s.clock()))
                            missing[kind]=max(0,missing[kind]-len(values));data['counts'][kind]+=len(values)
                    if isinstance(self.model,MaterialModel):
                        model=data.get('generation_model',{}).get('model','')
                        if isinstance(model,str) and model.endswith(':free'):self.model.prefer_free_model(model)
                state='waiting' if any(missing.values()) else 'ready'
                message=f"已准备文章 {min(data['counts']['thread'],1)}/1、评论 {min(data['counts']['reply'],p['payload'].get('replies_per_day',5))}/{p['payload'].get('replies_per_day',5)}"
                if not p['payload'].get('replies_per_day',5):message=f"已准备文章 {min(data['counts']['thread'],1)}/1；自动评论已关闭"
                if state=='waiting':message+=('；相关活跃原帖不足，稍后扩大查找，不填无关内容' if p['payload'].get('replies_per_day',5) else '；文章素材尚未通过检查，稍后继续准备')
            except Exception as ex:
                state='waiting';message=str(ex)[:200] if isinstance(ex,ValueError) else '原帖读取或模型连接暂未完成，保留已有素材并稍后重查'
            data['attempt_history'].append({'at':self.s.clock(),'attempt':attempts,'stage':stage,'state':state,'message':message})
            if state=='waiting':
                next_check=self.s.clock()+min(7200,1800*2**min(attempts-1,2))
                message+='；'+str(int((next_check-self.s.clock())/60))+'分钟后继续检查当天缺口'
        with self.store.connect(True) as db:
            db.execute('INSERT INTO community_preparations VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(plan_id,day) DO UPDATE SET state=excluded.state,message=excluded.message,attempts=excluded.attempts,next_check=excluded.next_check,fingerprint=excluded.fingerprint,data=excluded.data,updated=excluded.updated',(ident,day,state,message,attempts,next_check,fp,dumps(data),now,self.s.clock()))
            if state=='ready' and day==local.isoformat():
                db.execute('UPDATE community_plan_checks SET next_check=? WHERE plan_id=? AND day=? AND next_check>0',(self.s.clock(),ident,day))
        return {'message':message,'worked':any(missing.values()) or attempts>0}
