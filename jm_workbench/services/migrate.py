"""Explicit read-only import. Existing runtime and login profiles remain in place."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from ..core.db import dumps
from ..policies.rules import DEFAULTS
from .guard import CN


def timestamp(value):
    try:
        if isinstance(value, (int,float)):
            return value / 1000 if value > 10**11 else value
        return datetime.fromisoformat(value).replace(tzinfo=CN).timestamp()
    except (ValueError, TypeError):
        # Unknown dates conservatively block contact for the next seven days.
        return datetime.now(CN).timestamp()


def import_legacy(configuration, runtime, profile):
    cfg, store = configuration, configuration.store
    root, profile = Path(runtime).resolve(), Path(profile).resolve()
    if any(o['id'] == 'legacy-v1' for o in store.objects('migration')):
        return {'message': '历史数据已导入，不重复执行'}
    source = root/'f_layer'/'f_layer.db'
    if not source.is_file():
        raise ValueError('找不到既有业务数据库')
    old = sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)
    old.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        candidates = list(old.execute('SELECT * FROM adult_candidates')) if 'adult_candidates' in tables else []
        history = list(old.execute('SELECT * FROM f_publish_videos')) if 'f_publish_videos' in tables else []
        attempts = list(old.execute('SELECT * FROM adult_attempts')) if 'adult_attempts' in tables else []
        control = dict(old.execute('SELECT * FROM adult_control WHERE id=1').fetchone()) if 'adult_control' in tables else {}
    finally:
        old.close()
    authors = {}
    main_path = root/'database'/'sqlite_tables.db'
    if main_path.is_file():
        main = sqlite3.connect(main_path.as_uri()+'?mode=ro', uri=True)
        try:
            authors = {str(r[0]): str(r[1] or '') for r in main.execute('SELECT video_id,creator_hash FROM kuaishou_video')}
        finally:
            main.close()
    cfg.config.save({'crawler_root': str(root), 'crawler_python': str(root/'.venv'/'Scripts'/'python.exe')})
    account = cfg.account(dict(name='快手主账号', platform='ks', profile_dir=str(profile)), 'legacy-main-ks')
    # The old identity is a binding expectation, not a fresh login verification.
    account = store.put('account', dict(account, identity=control.get('account_id','')), account['id'])
    for kind, defaults in DEFAULTS.items():
        task = cfg.task(dict(platform='ks', kind=kind, **defaults), 'default-'+kind)
        cfg.binding(dict(task_id=task['id'], account_id=account['id']))
    task = cfg.task(dict(name='快手关键词采集',platform='ks',kind='crawler',keywords=['成人用品库存处理'], enabled=False), 'default-crawler')
    cfg.binding(dict(task_id=task['id'],account_id=account['id'],enabled=False))
    with store.connect(True) as db:
        for row in candidates:
            data = json.loads(row['payload'])
            db.execute('INSERT INTO evidence(run_id,platform,video_id,author_id,data,decision,reason,created) VALUES(?,?,?,?,?,?,?,?)',
                       ('legacy','ks',row['video_id'],data.get('author_id',''),dumps(data),'legacy',
                        '迁入历史记录，重新执行时按当前规则读取详情；未直接进入发布队列',row['updated_at']))
        for row in history:
            db.execute('INSERT OR IGNORE INTO history VALUES(?,?,?,?,?)', ('ks',row['video_id'],authors.get(row['video_id'],''),row['reply_text'] or '',timestamp(row['publish_time'])))
        for row in attempts:
            db.execute('INSERT OR IGNORE INTO history VALUES(?,?,?,?,?)', ('ks',row['video_id'],row['author_id'],row['comment'],timestamp(row['created_at'])))
        db.execute("INSERT INTO objects(kind,id,data) VALUES('migration','legacy-v1',?)", (dumps({'candidates':len(candidates),'history':len(history),'attempts':len(attempts)}),))
    if control.get('risk') or any(row['state'] in ('reserved','unknown') for row in attempts):
        store.lock('ks', '迁入既有风险状态，请核实原任务停止原因后处理')
    store.event(f'历史数据已导入：{len(candidates)}条候选、{len(history)}条接触记录；任务尚未启动')
    return {'candidates':len(candidates),'history':len(history),'attempts':len(attempts)}
