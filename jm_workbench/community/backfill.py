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
            ''')

    def _coverage(self, db, plan):
        """Plan attribution wins over sending date, including overnight sends."""
        account = plan['payload']['account_id']
        rows = db.execute('''SELECT j.*,i.day FROM community_jobs j
            LEFT JOIN community_plan_items i ON i.post_id=j.post_id
            WHERE j.account_id=? ORDER BY j.created,j.id''', (account,)).fetchall()
        coverage = {}
        from .service import SHANGHAI
        for r in rows:
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
            candidates = self.s.adapter.discover(a,p['source_boards']) if p['source_boards'] else []
            with self.store.connect(True) as db:self._fill(db,plan_id,candidates)
        return {'message':'已检查账号并补充可核验的原帖和草稿；尚未发布','backfill':self.state()}

    def state(self):
        items = []
        for r in self.store.rows('''SELECT b.*,a.data AS account_data FROM community_backfill b
            JOIN community_plans p ON p.id=b.plan_id
            JOIN community_accounts a ON a.id=json_extract(p.payload,'$.account_id')
            ORDER BY b.day,a.id,b.kind,b.slot'''):
            account = json.loads(r.pop('account_data'));r['platform'] = account['platform']
            jobs = self.s.jobs(r['post_id']) if r['post_id'] else []
            states = {j['state'] for j in jobs}
            r['status'] = ('needs_check' if states & {'unknown','failed','paused','cancelled'} else
                'submitted' if 'submitted' in states else 'recorded' if 'recorded' in states else
                'queued' if states & {'queued','running'} else 'draft' if r['post_id'] else
                'missing_target' if r['kind']=='reply' else 'missing_content')
            r['jobs'] = jobs
            if jobs:r['message'] = '；'.join(j['message'] for j in jobs if j.get('message')) or r['message']
            items.append(r)
        return {'items':items,'total':len(items),'threads':sum(r['kind']=='thread' for r in items),
                'replies':sum(r['kind']=='reply' for r in items),
                'submitted':sum(r['status']=='submitted' for r in items),
                'with_content':sum(bool(r['post_id']) for r in items)}
