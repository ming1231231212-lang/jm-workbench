"""Continue only a stored run's remaining targets; never repeat its search or sends."""
import json
import time
from ..core.db import dumps, uid
from ..policies.rules import assess_item, ID_RE
from ..policies.comments import candidates
from .guard import comment_due, contact_status, next_window


def continue_pending(cfg, source_id, now=None):
    now = time.time() if now is None else now
    store = cfg.store
    existing = store.rows('SELECT run_id FROM continuations WHERE source_run_id=?', (source_id,))
    if existing:
        return {'ok': True, 'created': False, 'run_id': existing[0]['run_id'], 'message': '这些剩余视频已建立补发任务，未重复添加'}
    rows = store.rows('SELECT * FROM runs WHERE id=?', (source_id,))
    if not rows:
        raise ValueError('原任务不存在')
    source = rows[0]
    if source['state'] not in ('completed', 'paused', 'failed'):
        raise ValueError('原任务仍在执行，请先停止后再继续剩余视频')
    old = json.loads(source['snapshot'])
    remaining = json.loads(source['progress']).get('pending', [])
    if not remaining or len(remaining) > 200:
        raise ValueError('没有可继续的剩余视频，或原队列数量异常')
    entries, errors = cfg.preflight(source['task_id'])
    matching = [r for r in entries+errors if r.get('account', {}).get('id') == source['account_id']]
    if len(matching) != 1 or matching[0]['reason']:
        raise ValueError(matching[0]['reason'] if matching else '原账号与任务的绑定未启用')
    row = matching[0]
    task, account = row['task'], row['account']
    if task['kind'] == 'crawler' or task['kind'] != old['task']['kind'] or task['platform'] != source['platform']:
        raise ValueError('业务或平台已改变，不能续接原发布队列')
    if account.get('identity') != old['account'].get('identity') or account['profile_dir'] != old['account']['profile_dir']:
        raise ValueError('必须使用原任务绑定的同一账号和浏览器资料')
    if task.get('publish_scope') != 'all_matches':
        raise ValueError('请将任务执行范围设为“所有符合条件的视频”，每个视频1条')
    due = comment_due(store, source['platform'], task, now)
    with store.connect(True) as db:
        existing = db.execute('SELECT run_id FROM continuations WHERE source_run_id=?', (source_id,)).fetchone()
        if existing:
            return {'ok': True, 'created': False, 'run_id': existing['run_id'], 'message': '这些剩余视频已建立补发任务，未重复添加'}
        for kind in ('task', 'account', 'binding'):
            current = db.execute('SELECT version FROM objects WHERE kind=? AND id=?', (kind, row[kind]['id'])).fetchone()
            if not current or current['version'] != row[kind]['version']:
                raise ValueError('配置已变化，请重新检查后补发')
        if db.execute("SELECT 1 FROM runs WHERE task_id=? AND account_id=? AND state IN ('queued','waiting','running')", (task['id'], account['id'])).fetchone():
            raise ValueError('此任务与账号已有活动队列，未重复创建')
        if db.execute('SELECT 1 FROM risk WHERE platform=?', (task['platform'],)).fetchone():
            raise ValueError('平台限制尚未解除')
        if db.execute("SELECT 1 FROM attempts WHERE platform=? AND state IN ('reserved','unknown')", (task['platform'],)).fetchone():
            raise ValueError('存在未确认发送，不能继续补发')
        pending, skipped, seen, inherited = [], [], set(), []
        for entry in remaining:
            vid = entry.get('video_id') if isinstance(entry, dict) else entry
            if not isinstance(vid, str) or not ID_RE.fullmatch(vid):
                raise ValueError('原队列视频标识异常')
            if vid in seen:
                continue
            seen.add(vid)
            item = None
            for evidence in db.execute('SELECT data FROM evidence WHERE run_id=? AND platform=? AND video_id=? ORDER BY id DESC', (source_id, task['platform'], vid)):
                candidate = json.loads(evidence['data'])
                if (candidate.get('source') or {}).get('kind') == 'search':
                    item = candidate
                    break
                origin = candidate.get('search_origin') or {}
                if origin.get('kind') == 'search' and origin.get('video_id') == vid:
                    item = dict(candidate, source={'kind': 'search', 'query': origin['query']})
                    break
            if not item or item.get('video_id') != vid:
                skipped.append({'video_id': vid, 'reason': '原队列缺少可核验的搜索证据'})
                continue
            if (item.get('source') or {}).get('query') not in task['keywords']:
                skipped.append({'video_id': vid, 'reason': '原来源关键词已不在当前配置中'})
                continue
            ok, reason = assess_item(task, item)
            if not ok:
                skipped.append({'video_id': vid, 'reason': reason})
                continue
            statuses = [contact_status(db, task['platform'], item, text, now) for text in candidates(task, item)]
            usable = [(reason, after) for reason, after in statuses if after is not None]
            if not usable:
                skipped.append({'video_id': vid, 'reason': statuses[0][0] if statuses else '缺少文案'})
                continue
            reason, after = min(usable, key=lambda value: value[1])
            pending.append({'video_id': vid, 'search_origin': {'kind': 'search', 'video_id': vid, 'query': item['source']['query']},
                            'not_before': after, 'wait_reason': reason})
            inherited.append(item)
        ident = uid()
        if pending:
            due = next_window(max(due, min(c['not_before'] for c in pending)), task['start_hour'], task['end_hour'])
        else:
            due = 0
        progress = {'keyword_index': len(task['keywords']), 'pending': pending, 'source_run_id': source_id,
                    'selected_count': len(seen), 'imported_count': len(pending), 'skipped': len(skipped), 'skipped_targets': skipped, 'sent': 0, 'collected': 0}
        snapshot = dict(row, revision=cfg.code_revision)
        message = f'剩余{len(seen)}个视频：已接入{len(pending)}个，跳过{len(skipped)}个；每个视频1条，发送前重新核验'
        db.execute('INSERT INTO runs(id,task_id,account_id,platform,state,snapshot,progress,created,updated,due,message) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (ident, task['id'], account['id'], task['platform'], ('waiting' if due>now else 'queued') if pending else 'completed',
                    dumps(snapshot), dumps(progress), now, now, due, message))
        db.execute('INSERT INTO continuations VALUES(?,?)', (source_id, ident))
        for item in inherited:
            db.execute('INSERT INTO evidence(run_id,platform,video_id,author_id,data,decision,reason,created) VALUES(?,?,?,?,?,?,?,?)',
                       (ident, task['platform'], item['video_id'], item['author_id'], dumps(item), 'checking',
                        '沿用原任务搜索证据；发送前仍须重新核验详情', now))
    store.event(message, ident)
    return {'ok': True, 'created': True, 'run_id': ident, 'queued': len(pending), 'skipped': skipped, 'message': message}
