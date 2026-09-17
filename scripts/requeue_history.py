"""Recheck one historical batch and append to a compatible waiting continuation.

Default is read-only. --apply is an explicit enqueue action, never a direct send.
This maintenance entrypoint does not change running code or frozen run snapshots.
"""
import argparse
import json
import time
from collections import Counter
from pathlib import Path

from jm_workbench.core.config import Config, revision
from jm_workbench.core.db import Store, dumps
from jm_workbench.policies.rules import ID_RE, assess_item
from jm_workbench.policies.comments import candidates
from jm_workbench.services.configuration import Configuration
from jm_workbench.services.guard import contact_status, comment_due, next_window


def requeue_history(cfg, source_id, *, apply=False, now=None):
    now = time.time() if now is None else now
    store = cfg.store
    sources = store.rows('SELECT * FROM runs WHERE id=?', (source_id,))
    if not sources:
        raise ValueError('原任务不存在')
    source = sources[0]
    if source['state'] != 'completed':
        raise ValueError('仅复筛已经完成的历史批次')
    old = json.loads(source['snapshot'])
    entries, errors = cfg.preflight(source['task_id'])
    rows = [r for r in entries+errors if r.get('account', {}).get('id') == source['account_id']]
    if len(rows) != 1 or rows[0]['reason']:
        raise ValueError(rows[0]['reason'] if rows else '原任务与账号绑定未启用')
    current = rows[0]
    task, account = current['task'], current['account']
    if (task['kind'] != 'adult_comments' or old['task']['kind'] != task['kind']
            or task.get('adult_target') != 'keyword' or task.get('publish_scope') != 'all_matches'
            or task.get('comments_per_video') != 1 or task['platform'] != source['platform']):
        raise ValueError('仅支持按关键词匹配、每视频1条的成人用品原任务')
    if any(account.get(k) != old['account'].get(k) for k in ('identity', 'profile_dir', 'platform')):
        raise ValueError('原账号身份或资料目录已变化')
    if revision() != cfg.code_revision:
        raise ValueError('代码已变化，请重新核验')
    due = comment_due(store, task['platform'], task, now)
    with store.connect(immediate=apply) as db:
        if not apply:
            db.execute('BEGIN')  # consistent read-only preview
        existing = db.execute('SELECT run_id FROM continuations WHERE source_run_id=?', (source_id,)).fetchone()
        if existing:
            return {'created': False, 'run_id': existing['run_id'], 'message': '该批次已接入补发，未重复添加'}
        for kind in ('task', 'account', 'binding'):
            obj = current[kind]
            row = db.execute('SELECT version FROM objects WHERE kind=? AND id=?', (kind, obj['id'])).fetchone()
            if not row or row['version'] != obj['version']:
                raise ValueError('配置已变化，请重新核验')
        if db.execute('SELECT 1 FROM risk WHERE platform=?', (task['platform'],)).fetchone():
            raise ValueError('平台限制尚未解除')
        if db.execute("SELECT 1 FROM attempts WHERE platform=? AND state IN ('reserved','unknown')", (task['platform'],)).fetchone():
            raise ValueError('存在未确认发送，不能补发')
        active = [dict(r) for r in db.execute("SELECT * FROM runs WHERE platform=? AND state IN ('queued','waiting','running')", (task['platform'],))]
        targets = [r for r in active if r['task_id'] == task['id'] and r['account_id'] == account['id']]
        if len(targets) != 1 or targets[0]['state'] not in ('queued', 'waiting'):
            raise ValueError('需要同一任务与账号的等待队列；执行中不能合并')
        target = targets[0]
        snapshot, progress = json.loads(target['snapshot']), json.loads(target['progress'])
        if snapshot['revision'] != cfg.code_revision or any(snapshot[k] != current[k] for k in ('task','account','binding')):
            raise ValueError('等待队列快照与当前配置不一致')
        if not progress.get('source_run_id') or progress.get('keyword_index', 0) < len(task['keywords']):
            raise ValueError('仅可合并到不再搜索的补发队列')
        queued = {p['video_id'] if isinstance(p, dict) else p for r in active for p in json.loads(r['progress']).get('pending', [])}
        evidence = list(db.execute('SELECT * FROM evidence WHERE run_id=? AND platform=? ORDER BY id DESC LIMIT 2001', (source_id, task['platform'])))
        if not evidence or len(evidence) > 2000:
            raise ValueError('原批次证据为空或数量异常')
        groups = {}
        for r in evidence:
            groups.setdefault(r['video_id'], []).append(r)
        if len(groups) > 200:
            raise ValueError('原批次目标数量异常')
        counts, pending, inherited, decisions = Counter(), [], [], []
        for vid, records in groups.items():
            item = None
            reason = '正文不匹配或缺少准确搜索来源'
            for r in records:
                value = json.loads(r['data'])
                origin = value.get('source') or {}
                if (not ID_RE.fullmatch(str(vid)) or value.get('video_id') != vid
                        or not ID_RE.fullmatch(str(value.get('author_id', '')))
                        or origin.get('kind') != 'search' or origin.get('query') not in old['task']['keywords']
                        or origin.get('query') not in task['keywords']):
                    continue
                ok, reason = assess_item(task, value)
                if ok:
                    item = value
                    break
            if item is None:
                state = 'rejected'
            else:
                counts['matched'] += 1
                statuses = [contact_status(db, task['platform'], item, text, now) for text in candidates(task, item)]
                usable = [(reason, after) for reason, after in statuses if after is not None]
                if not usable:
                    state, reason = 'contacted', '该视频已有接触记录'
                elif vid in queued:
                    state, reason = 'already_queued', '该视频已在执行队列中'
                else:
                    state = 'added'
                    reason, after = min(usable, key=lambda value: value[1])
                    pending.append({'video_id': vid, 'search_origin': {'kind':'search','video_id':vid,'query':item['source']['query']},
                                    'not_before': after, 'wait_reason': reason, 'source_run_id': source_id})
                    inherited.append(item)
            counts[state] += 1
            decisions.append({'video_id': vid, 'state': state, 'reason': reason})
        summary = {'source_run_id': source_id, 'records': len(evidence), 'unique': len(groups),
                   **{k: counts[k] for k in ('matched','added','already_queued','contacted','rejected')}}
        message = (f'历史采集{summary["records"]}条复筛：{summary["unique"]}个视频中{summary["matched"]}个匹配；'
                   f'新增{summary["added"]}个，{summary["already_queued"]}个已排队、{summary["contacted"]}个已接触；每视频1条，发送前重新核验')
        if apply:
            progress.setdefault('pending', []).extend(pending)
            progress['selected_count'] = progress.get('selected_count', 0)+len(pending)
            progress['imported_count'] = progress.get('imported_count', 0)+len(pending)
            progress.setdefault('batch_rechecks', []).append(dict(summary, checked_at=now, decisions=decisions))
            if progress['pending']:
                due = next_window(max(due, min(p.get('not_before', 0) if isinstance(p, dict) else 0 for p in progress['pending'])), task['start_hour'], task['end_hour'])
            db.execute('UPDATE runs SET progress=?,message=?,updated=?,due=? WHERE id=?',
                       (dumps(progress), message, now, due, target['id']))
            for item in inherited:
                db.execute('INSERT INTO evidence(run_id,platform,video_id,author_id,data,decision,reason,created) VALUES(?,?,?,?,?,?,?,?)',
                           (target['id'],task['platform'],item['video_id'],item['author_id'],dumps(item),'checking',
                            '历史批次按当前规则复筛；沿用搜索来源，发送前必须重读详情',now))
            db.execute('INSERT INTO continuations VALUES(?,?)', (source_id, target['id']))
            db.execute('INSERT INTO events(run_id,level,message,created) VALUES(?,?,?,?)', (target['id'],'info',message,now))
        return {'created': apply, 'run_id': target['id'], 'summary': summary, 'pending': pending, 'decisions': decisions, 'message': message}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_run_id')
    parser.add_argument('--home')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--output')
    args = parser.parse_args()
    config = Config(args.home)
    cfg = Configuration(config, Store(config.home/'jm.db'))
    result = requeue_history(cfg, args.source_run_id, apply=args.apply)
    value = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(value, encoding='utf-8')
    print(value)


if __name__ == '__main__':
    main()
