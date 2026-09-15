import json
import time
from datetime import datetime, timedelta, timezone
from ..core.db import dumps, uid
from ..policies.rules import detail_ready, validate_template
from ..policies.comments import candidates

CN = timezone(timedelta(hours=8))


def next_window(now, start=8, end=23):
    dt = datetime.fromtimestamp(now, CN)
    if start <= dt.hour < end:
        return now
    target = dt.replace(hour=start, minute=0, second=0, microsecond=0)
    if dt.hour >= end:
        target += timedelta(days=1)
    return target.timestamp()


def read_slot(store, platform, now):
    due = next_window(now)
    with store.connect(True) as db:
        rows = db.execute('SELECT created FROM reads WHERE platform=? AND created>? ORDER BY created',
                          (platform, now - 86400)).fetchall()
        if rows:
            due = max(due, rows[-1]['created'] + 300)
        if len(rows) >= 24:
            due = max(due, rows[-24]['created'] + 86400 + 1)
        if due <= now:
            db.execute('INSERT INTO reads VALUES(?,?)', (platform, now))
    return due


def comment_due(store, platform, task, now):
    due = next_window(now, task['start_hour'], task['end_hour'])
    rows = store.rows('SELECT created FROM attempts WHERE platform=? AND created>? ORDER BY created', (platform, now - 86400))
    if rows:
        due = max(due, rows[-1]['created'] + 1800)
    if len(rows) >= 5:
        due = max(due, rows[-5]['created'] + 86400 + 1)
    return next_window(due, task['start_hour'], task['end_hour'])


def contact_reason(db, platform, item, text, now):
    vid, author = item['video_id'], item['author_id']
    for table in ('attempts', 'history'):
        if db.execute(f'SELECT 1 FROM {table} WHERE platform=? AND video_id=?', (platform, vid)).fetchone():
            return '该视频已有接触记录'
        if db.execute(f'SELECT 1 FROM {table} WHERE platform=? AND author_id=? AND created>?', (platform, author, now - 7 * 86400)).fetchone():
            return '近7天已联系该作者'
        if db.execute(f'SELECT 1 FROM {table} WHERE platform=? AND content=? AND created>?', (platform, text, now - 7 * 86400)).fetchone():
            return '近7天已使用同一评论文本'
    return ''


def reserve(store, run, item, text, now):
    task, account = run['snapshot']['task'], run['snapshot']['account']
    ok, reason = detail_ready(task['kind'], item, task.get('adult_target', 'inventory'), task['keywords'])
    if not ok:
        raise ValueError(reason)
    validate_template(task['kind'], text)
    if task.get('comment_mode') == 'core_variants' and text not in candidates(task, item):
        raise ValueError('文案与该视频的核心句生成结果不一致')
    if not 0 <= now - item.get('observed_at', 0) <= 120:
        raise ValueError('详情证据已过期')
    if item['author_id'] == account['identity']:
        raise ValueError('不对当前账号自己的视频发布招募或收货评论')
    with store.connect(True) as db:
        state = db.execute('SELECT state FROM runs WHERE id=?', (run['id'],)).fetchone()
        if not state or state['state'] != 'running':
            raise ValueError('任务已停止')
        if db.execute('SELECT 1 FROM risk WHERE platform=?', (task['platform'],)).fetchone():
            raise ValueError('平台已停止执行')
        if db.execute("SELECT 1 FROM attempts WHERE platform=? AND state IN ('reserved','unknown')", (task['platform'],)).fetchone():
            raise ValueError('存在结果未确认的发送，不再继续')
        # Enforce again inside the same transaction as the reservation.
        recent = db.execute('SELECT created FROM attempts WHERE platform=? AND created>? ORDER BY created', (task['platform'], now-86400)).fetchall()
        if len(recent) >= 5 or (recent and now - recent[-1]['created'] < 1800) or next_window(now, task['start_hour'], task['end_hour']) != now:
            raise ValueError('未到允许发送的时间或配额')
        reason = contact_reason(db, task['platform'], item, text, now)
        if reason:
            raise ValueError(reason)
        ident = uid()
        db.execute('INSERT INTO attempts(id,platform,video_id,author_id,account_id,run_id,content,evidence,state,created) '
                   'VALUES(?,?,?,?,?,?,?,?,?,?)', (ident, task['platform'], item['video_id'], item['author_id'], account['id'],
                   run['id'], text, dumps(item), 'reserved', now))
    return ident


def finish(store, ident, receipt):
    row = store.rows('SELECT * FROM attempts WHERE id=?', (ident,))[0]
    state = 'sent' if receipt.get('ok') and receipt.get('comment_id') else 'not_sent' if receipt.get('not_sent') else 'unknown'
    with store.connect() as db:
        db.execute('UPDATE attempts SET state=?,receipt=? WHERE id=?', (state, dumps(receipt), ident))
    if state == 'unknown':
        store.lock(row['platform'], '评论结果不确定，已停止同平台任务；不能自动重发')
    return state


def recover(store):
    with store.connect(True) as db:
        platforms = [r[0] for r in db.execute("SELECT DISTINCT platform FROM attempts WHERE state='reserved'")]
        db.execute("UPDATE attempts SET state='unknown' WHERE state='reserved'")
        db.execute("UPDATE runs SET state='paused',message='服务重启，中断任务已停止，请重新执行' WHERE state='running'")
    for platform in platforms:
        store.lock(platform, '服务重启时存在未确认发送，停止同平台任务且不重发')
