"""Historical obligations, separate from actual submission dates and receipts."""
import hashlib
import json
from datetime import date, datetime, timedelta
from .models import CommunityPost
from .daily import material_id, eligible
from .registry import thread_url
from ..core.db import dumps, uid


class Backfill:
    def __init__(self, service):
        self.s, self.store = service, service.store
        with self.store.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS community_backfill(
              id TEXT PRIMARY KEY,plan_id TEXT,day TEXT,kind TEXT,slot INTEGER,
              post_id TEXT DEFAULT '',created REAL,message TEXT DEFAULT '',
              UNIQUE(plan_id,day,kind,slot));
            CREATE UNIQUE INDEX IF NOT EXISTS community_backfill_post
              ON community_backfill(post_id) WHERE post_id!='';
            CREATE TABLE IF NOT EXISTS community_backfill_continuations(
              old_job_id TEXT PRIMARY KEY,new_job_id TEXT UNIQUE,post_id TEXT,
              old_state TEXT,old_message TEXT,created REAL);
            ''')

    def _coverage(self, db, plan):
        """Plan attribution wins over sending date, including overnight sends."""
        account = plan['payload']['account_id']
        rows = db.execute('''SELECT j.*,i.day FROM community_jobs j
            LEFT JOIN community_plan_items i ON i.post_id=j.post_id
            WHERE j.account_id=? ORDER BY j.created,j.rowid''', (account,)).fetchall()
        coverage = {}
        from .service import SHANGHAI
        latest = {r['post_id']:r['id'] for r in rows}
        for r in rows:
            if latest[r['post_id']] != r['id']:continue
            if not r['day'] and r['state'] not in ('submitted', 'recorded'):
                continue
            day = r['day'] or datetime.fromtimestamp(r['started'] if r['state']=='submitted' else r['updated'], SHANGHAI).date().isoformat()
            kind = json.loads(r['snapshot'])['payload'].get('kind', 'thread')
            coverage.setdefault((day, kind), []).append(dict(r))
        return coverage

    def preview(self, plan_ids, through_day, replies_per_day=5, db=None):
        from .service import SHANGHAI
        if db is None:
            with self.store.connect() as conn:
                return self.preview(plan_ids, through_day, replies_per_day, conn)
        end = date.fromisoformat(str(through_day))
        today = datetime.fromtimestamp(self.s.clock(), SHANGHAI).date()
        if end >= today:raise ValueError('历史补录只包含昨天及之前；今天仍使用当日计划')
        if not 0 <= replies_per_day <= 5:raise ValueError('每日评论目标为0至5条')
        slots = []
        for ident in dict.fromkeys(plan_ids):
            row = db.execute('SELECT * FROM community_plans WHERE id=?', (ident,)).fetchone()
            if not row:raise ValueError('每日计划不存在')
            plan = dict(row);plan['payload'] = json.loads(plan['payload'])
            account = db.execute('SELECT data FROM community_accounts WHERE id=?', (plan['payload']['account_id'],)).fetchone()
            if not account:raise ValueError('原账号已删除')
            if json.loads(account['data'])['platform'] not in ('tieba','juejin'):
                raise ValueError('历史补录首批仅适用于已接入的贴吧和掘金计划')
            if not db.execute('SELECT 1 FROM community_plan_days WHERE plan_id=?', (ident,)).fetchone():
                raise ValueError('尚未开始执行的计划没有历史补发范围')
            start = datetime.fromtimestamp(plan['created'], SHANGHAI).date()
            if (end-start).days > 90:raise ValueError('单次最多核对91天')
            coverage = self._coverage(db, plan)
            while start <= end:
                day = start.isoformat()
                for kind, goal in (('thread', 1), ('reply', replies_per_day)):
                    rows = coverage.get((day, kind), [])
                    # Successful or user-recorded publications take the quota first.
                    rows.sort(key=lambda r:(r['state'] not in ('submitted','recorded'),r['created'],r['id']))
                    for index in range(goal):
                        old = rows[index] if index < len(rows) else None
                        if old and old['state'] in ('submitted','recorded'):continue
                        slots.append({'plan_id':ident,'day':day,'kind':kind,'slot':index+1,
                                      'post_id':old['post_id'] if old else ''})
                start += timedelta(days=1)
        return slots

    def register(self, plan_ids, through_day, replies_per_day=5):
        now = self.s.clock();created = 0
        with self.s.step_lock, self.store.connect(True) as db:
            for slot in self.preview(plan_ids, through_day, replies_per_day, db):
                created += db.execute('''INSERT OR IGNORE INTO community_backfill
                    (id,plan_id,day,kind,slot,post_id,created,message) VALUES(?,?,?,?,?,?,?,?)''',
                    (uid(),slot['plan_id'],slot['day'],slot['kind'],slot['slot'],slot['post_id'],now,'历史缺口已登记，尚未补发')).rowcount
            self._fill(db)
        return {'message':f'新增登记{created}项历史缺口；已有记录保持，未重复发帖或评论',
                'created':created,'backfill':self.state()}

    def _used(self, db, aid):
        bodies, targets = set(), set()
        for row in db.execute('SELECT payload FROM community_posts'):
            p = json.loads(row['payload'])
            for t in p['targets']:
                if t['account_id'] != aid:continue
                bodies.add(material_id(p['body']))
                if p.get('kind')=='reply':targets.add(t['destination'])
        return bodies, targets

    def _fill(self, db, only_plan=None, candidates=()):
        plans = {}
        for row in db.execute("SELECT * FROM community_backfill WHERE post_id='' ORDER BY day,kind,id").fetchall():
            r = dict(row)
            if only_plan and r['plan_id']!=only_plan:continue
            if r['plan_id'] not in plans:
                p = self.s.daily.get(r['plan_id'])['payload']
                a = self.s.account(p['account_id'])
                bodies, targets = self._used(db, a['id'])
                plans[r['plan_id']] = (p,a,bodies,targets)
            p,a,bodies,targets = plans[r['plan_id']]
            if r['kind']=='reply' and not p.get('replies_per_day',5):continue
            selected = None
            materials = p['topics'] if r['kind']=='thread' else p['replies']
            for material in materials:
                if material_id(material['body']) in bodies:continue
                if r['kind']=='reply' and material['url'] in targets:continue
                selected = material;break
            if not selected and r['kind']=='reply' and only_plan:
                for c in candidates:
                    try:url = thread_url(a['platform'],c['url'])
                    except (ValueError,KeyError):continue
                    if url in targets or not c.get('author_id') or c['author_id']==a['identity']:continue
                    rule = next((x for x in p['reply_rules'] if material_id(x['body']) not in bodies and eligible(x,c)),None)
                    if rule:
                        selected = {**c,'url':url,'body':rule['body']};break
            if not selected:
                db.execute('UPDATE community_backfill SET message=? WHERE id=?',
                    ('尚缺未使用的帖子正文' if r['kind']=='thread' else '待连接账号后匹配相关原帖；不使用无关评论补数',r['id']))
                continue
            target = p['board'] if r['kind']=='thread' else selected['url']
            payload = CommunityPost(request_id='backfill-'+hashlib.sha256(r['id'].encode()).hexdigest()[:32],
                kind=r['kind'],title=selected['title'] if r['kind']=='thread' else '回复：'+selected['title'][:27],
                body=selected['body'],source_title=selected.get('title','') if r['kind']=='reply' else '',
                source_excerpt=selected.get('excerpt','') if r['kind']=='reply' else '',
                category=p['board'] if a['platform']=='juejin' and r['kind']=='thread' else '',
                platform_tags=selected.get('platform_tags',[]) if r['kind']=='thread' else selected.get('source_tags',[])[:3],
                targets=[{'account_id':a['id'],'destination':target}])
            if a['platform']=='juejin':
                from .juejin import validate_payload
                validate_payload(payload.model_dump(),target)
            post = self.s.save(payload,_db=db)['id']
            db.execute('UPDATE community_backfill SET post_id=?,message=? WHERE id=?',
                (post,'正文已补入内容记录；需核验执行连接后安排实际发布',r['id']))
            bodies.add(material_id(selected['body']))
            if r['kind']=='reply':targets.add(target)

    def prepare(self, plan_id):
        """Read-only discovery and draft preparation; no launch or identity bypass."""
        p = self.s.daily.get(plan_id)['payload'];aid = p['account_id']
        if self.store.rows('SELECT 1 FROM community_risk WHERE platform=?', (self.s.account(aid)['platform'],)):
            raise ValueError('平台存在限制或不确定结果，请先核实')
        with self.s.step_lock:
            a = self.s.account(aid,True)
            if hasattr(self.s.adapter,'ensure_connection'):self.s.adapter.ensure_connection(a)
            self.s.check_account(aid)
            candidates = self.s.adapter.discover(a,p['source_boards']) if p['source_boards'] and p.get('replies_per_day',5) else []
            with self.store.connect(True) as db:self._fill(db,plan_id,candidates)
        return {'message':'已检查账号并补充可核验的原帖和草稿；尚未发布','backfill':self.state()}

    def state(self):
        items = []
        for r in self.store.rows('''SELECT b.*,p.payload AS plan_payload,a.data AS account_data FROM community_backfill b
            JOIN community_plans p ON p.id=b.plan_id
            JOIN community_accounts a ON a.id=json_extract(p.payload,'$.account_id')
            ORDER BY b.day,a.id,b.kind,b.slot'''):
            account = json.loads(r.pop('account_data'));r['platform'] = account['platform']
            replies_enabled=json.loads(r.pop('plan_payload')).get('replies_per_day',5)>0
            jobs = self.s.jobs(r['post_id']) if r['post_id'] else []
            # Earlier attempts remain visible with their original receipts.
            states = {jobs[-1]['state']} if jobs else set()
            r['status'] = ('needs_check' if states & {'unknown','failed','paused','cancelled'} else
                'submitted' if 'submitted' in states else 'recorded' if 'recorded' in states else
                'running' if 'running' in states else 'queued' if 'queued' in states else 'manual' if 'manual' in states else 'draft' if r['post_id'] else
                'missing_target' if r['kind']=='reply' else 'missing_content')
            r['jobs'] = jobs
            if jobs:r['message'] = jobs[-1].get('message') or r['message']
            if r['kind']=='reply' and not replies_enabled and not states & {'submitted','recorded','unknown','running'}:
                r['status']='cancelled';r['message']='自动评论已关闭，不再安排补发；原内容与记录保留'
            items.append(r)
        return {'items':items,'total':len(items),'threads':sum(r['kind']=='thread' for r in items),
                'replies':sum(r['kind']=='reply' for r in items),
                'submitted':sum(r['status']=='submitted' for r in items),
                'with_content':sum(bool(r['post_id']) for r in items)}

    def queue(self, plan_id, *, today_only=False):
        """Explicitly continue only proven-unsent history under the current revision."""
        from .service import revision,SHANGHAI
        with self.s.step_lock:
            p=self.s.daily.get(plan_id)
            if p['state']!='enabled':raise ValueError('请先核验并启用原每日计划，再安排历史补发')
            a=self.s.account(p['payload']['account_id'],True)
            if hasattr(self.s.adapter,'ensure_connection'):self.s.adapter.ensure_connection(a)
            self.s.check_account(a['id'])
            queued=0;skipped=0
            with self.store.connect(True) as db:
                current=db.execute('SELECT * FROM community_plans WHERE id=?',(plan_id,)).fetchone()
                raw=db.execute('SELECT * FROM community_accounts WHERE id=?',(a['id'],)).fetchone()
                if (current['state']!='enabled' or not json.loads(raw['data'])['enabled'] or
                    raw['version']!=current['account_version'] or raw['identity']!=current['identity'] or
                    current['revision']!=self.s.cfg.code_revision or revision()!=self.s.cfg.code_revision):
                    raise ValueError('计划或账号配置已改变，请重新核验')
                if db.execute('SELECT 1 FROM community_risk WHERE platform=?',(a['platform'],)).fetchone():
                    raise ValueError('平台仍有限制或结果不明，不能安排补发')
                if today_only:
                    day=datetime.fromtimestamp(self.s.clock(),SHANGHAI).date().isoformat()
                    rows=db.execute("SELECT i.*,i.post_id AS id FROM community_plan_items i WHERE plan_id=? AND day=? ORDER BY CASE kind WHEN 'thread' THEN 0 ELSE 1 END",(plan_id,day)).fetchall()
                else:
                    rows=db.execute("SELECT * FROM community_backfill WHERE plan_id=? AND post_id!='' ORDER BY CASE kind WHEN 'thread' THEN 0 ELSE 1 END,day,slot",(plan_id,)).fetchall()
                for r in rows:
                    if r['kind']=='reply' and not p['payload'].get('replies_per_day',5):
                        skipped+=1;continue
                    db.execute('SAVEPOINT backfill_queue')
                    try:
                        post=db.execute('SELECT * FROM community_posts WHERE id=?',(r['post_id'],)).fetchone()
                        payload=json.loads(post['payload'])
                        jobs=db.execute('SELECT * FROM community_jobs WHERE post_id=? ORDER BY created,rowid',(r['post_id'],)).fetchall()
                        if jobs and jobs[-1]['state'] in ('queued','running','submitted','recorded','manual','unknown'):
                            continue
                        old=jobs[-1] if jobs else None
                        if old:
                            receipt=json.loads(old['receipt']);snap=json.loads(old['snapshot'])
                            resolved=(old['state']=='not_sent' and receipt.get('phase')=='resolved_not_sent' and receipt.get('submitted') is False and len(receipt.get('note','').strip())>=12)
                            safe=(old['started']==0 and (not receipt or (receipt.get('phase')=='preflight' and receipt.get('submitted') is False) or resolved))
                            if old['state'] not in ('paused','failed','not_sent') or not safe or (old['state']=='failed' and not receipt):
                                raise ValueError('原任务缺少明确未提交证据，保留原记录')
                            if any(j['started'] or j['state'] in ('submitted','recorded','unknown','manual','running') for j in jobs):
                                raise ValueError('存在提交或不确定历史，不能自动补发')
                            if (old['account_id']!=a['id'] or snap['account']['identity']!=raw['identity'] or
                                snap['account']['version']!=raw['version'] or snap['payload']!=payload or
                                payload['targets']!=[{'account_id':a['id'],'destination':snap['destination']}]):
                                raise ValueError('原账号或内容已改变，不能续接历史任务')
                            db.execute("UPDATE community_jobs SET state='cancelled',message='明确未提交；已建立可追溯的历史补发后续任务',updated=? WHERE id=?",(self.s.clock(),old['id']))
                            db.execute('DELETE FROM community_claims WHERE job_id=?',(old['id'],))
                            db.execute("UPDATE community_posts SET state='draft' WHERE id=?",(r['post_id'],))
                        elif post['state']!='draft':raise ValueError('原内容状态不支持补发')
                        self.s.launch(r['post_id'],_db=db)
                        new=db.execute('SELECT id FROM community_jobs WHERE post_id=? ORDER BY created DESC,rowid DESC LIMIT 1',(r['post_id'],)).fetchone()
                        if old:
                            db.execute('INSERT INTO community_backfill_continuations VALUES(?,?,?,?,?,?)',
                                (old['id'],new['id'],r['post_id'],old['state'],old['message'],self.s.clock()))
                        db.execute('INSERT OR IGNORE INTO community_plan_items VALUES(?,?,?,?,?)',
                            (plan_id,r['day'],r['kind'],material_id(payload['body']),r['post_id']))
                        db.execute('UPDATE community_backfill SET message=? WHERE id=?',('已排队；与每日任务共用频率和额度，尚未发布',r['id']))
                        queued+=1
                    except ValueError as ex:
                        db.execute('ROLLBACK TO backfill_queue')
                        db.execute('UPDATE community_backfill SET message=? WHERE id=?',(str(ex),r['id']))
                        skipped+=1
                    finally:db.execute('RELEASE backfill_queue')
            return {'message':f'已安排{queued}项'+('今日未提交任务' if today_only else '历史补发')+f'，{skipped}项需继续核实；实际结果以平台回执为准',
                    'queued':queued,'skipped':skipped,'backfill':self.state()}
