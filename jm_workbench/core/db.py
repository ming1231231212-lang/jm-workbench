import contextlib
import json
import sqlite3
import time
import uuid


def uid():
    return uuid.uuid4().hex[:16]


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS objects(kind TEXT, id TEXT, data TEXT NOT NULL,
              version INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, task_id TEXT, account_id TEXT,
              platform TEXT, state TEXT, snapshot TEXT, progress TEXT DEFAULT '{}',
              created REAL, updated REAL, due REAL DEFAULT 0, message TEXT DEFAULT '');
            CREATE UNIQUE INDEX IF NOT EXISTS active_binding ON runs(task_id,account_id)
              WHERE state IN ('queued','running','waiting');
            CREATE TABLE IF NOT EXISTS evidence(id INTEGER PRIMARY KEY, run_id TEXT, platform TEXT,
              video_id TEXT, author_id TEXT, data TEXT, decision TEXT, reason TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, platform TEXT, video_id TEXT,
              author_id TEXT, account_id TEXT, run_id TEXT, content TEXT, evidence TEXT,
              state TEXT, receipt TEXT DEFAULT '{}', created REAL, UNIQUE(platform,video_id));
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, run_id TEXT, level TEXT,
              message TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS risk(platform TEXT PRIMARY KEY, reason TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS reads(platform TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS history(platform TEXT, video_id TEXT, author_id TEXT,
              content TEXT, created REAL, PRIMARY KEY(platform,video_id));
            ''')

    @contextlib.contextmanager
    def connect(self, immediate=False):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            if immediate:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def rows(self, sql, args=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args)]

    def objects(self, kind):
        return [dict(json.loads(r['data']), id=r['id'], version=r['version'])
                for r in self.rows('SELECT * FROM objects WHERE kind=? ORDER BY rowid', (kind,))]

    def get(self, kind, ident):
        values = self.rows('SELECT * FROM objects WHERE kind=? AND id=?', (kind, ident))
        if not values:
            raise ValueError('配置不存在')
        r = values[0]
        return dict(json.loads(r['data']), id=r['id'], version=r['version'])

    def put(self, kind, value, ident=None):
        ident = ident or uid()
        value = {k: v for k, v in value.items() if k not in ('id', 'version')}
        with self.connect(True) as db:
            if kind in ('account', 'task') and db.execute(
                "SELECT 1 FROM runs WHERE (account_id=? OR task_id=?) AND state IN ('running','queued','waiting')",
                (ident, ident)).fetchone():
                raise ValueError('请先停止该配置的活动任务，再编辑')
            db.execute('INSERT INTO objects(kind,id,data) VALUES(?,?,?) ON CONFLICT(kind,id) '
                       'DO UPDATE SET data=excluded.data,version=objects.version+1', (kind, ident, dumps(value)))
        return self.get(kind, ident)

    def event(self, message, run_id='', level='info'):
        with self.connect() as db:
            db.execute('INSERT INTO events(run_id,level,message,created) VALUES(?,?,?,?)',
                       (run_id, level, message[:600], time.time()))

    def lock(self, platform, reason):
        with self.connect(True) as db:
            db.execute('INSERT OR REPLACE INTO risk VALUES(?,?,?)', (platform, reason, time.time()))
            db.execute("UPDATE runs SET state='paused',message=?,updated=? WHERE platform=? "
                       "AND state IN ('queued','running','waiting')", (reason, time.time(), platform))
        self.event(reason, level='risk')

    def stop(self, run_id=None):
        with self.connect(True) as db:
            sql = "UPDATE runs SET state='paused',message='已停止；进行中的请求完成后不再执行下一步',updated=? WHERE state IN ('queued','running','waiting')"
            args = [time.time()]
            if run_id:
                sql += ' AND id=?'
                args.append(run_id)
            db.execute(sql, args)
        self.event('用户停止任务', run_id or '')

    def add_evidence(self, run_id, platform, data, decision, reason):
        with self.connect() as db:
            db.execute('INSERT INTO evidence(run_id,platform,video_id,author_id,data,decision,reason,created) '
                       'VALUES(?,?,?,?,?,?,?,?)', (run_id, platform, str(data.get('video_id', data.get('note_id', ''))),
                       str(data.get('author_id', data.get('user_id', ''))), dumps(data), decision, reason, time.time()))
