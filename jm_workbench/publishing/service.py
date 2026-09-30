import json
import mimetypes
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from ..core.config import revision
from ..core.db import dumps, uid
from .models import MAX_UPLOAD, PLATFORMS, PublishingSettings
from .sau import SAUBridge, SAUUnavailable, filename, sha256, under


def public(value):
    return {k: v for k, v in value.items() if not k.startswith('_')}


def probe_video(path):
    executable = shutil.which('ffprobe')
    if not executable:
        raise ValueError('未找到 ffprobe，无法验证视频文件，请先安装 FFmpeg')
    try:
        result = subprocess.run([executable, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                 'stream=codec_type,width,height:format=duration', '-of', 'json', str(path)],
                                capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        info = json.loads(result.stdout)
        stream = info['streams'][0]
        duration = float(info['format']['duration'])
        if result.returncode or stream['codec_type'] != 'video' or duration <= 0:
            raise ValueError()
        return {'duration': round(duration, 2), 'width': int(stream['width']), 'height': int(stream['height'])}
    except (ValueError, KeyError, IndexError, OSError, subprocess.SubprocessError):
        raise ValueError('文件不是可读取的视频，或视频已损坏')


class Publishing:
    def __init__(self, cfg, bridge=None, clock=time.time, probe=probe_video):
        self.cfg, self.store, self.clock, self.probe = cfg, cfg.store, clock, probe
        self.bridge = bridge or SAUBridge(cfg.config)
        self.media = cfg.config.home / 'publishing-media'
        self.media.mkdir(exist_ok=True)
        self.shutdown = threading.Event()
        self.step_lock = threading.Lock()
        self.thread = None
        with self.store.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS publish_media(id TEXT PRIMARY KEY, name TEXT, ref TEXT,
              size INTEGER, sha TEXT UNIQUE, info TEXT, created REAL, sau_ref TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS publish_batches(id TEXT PRIMARY KEY, request_id TEXT UNIQUE,
              payload TEXT, state TEXT DEFAULT 'draft', created REAL, updated REAL);
            CREATE TABLE IF NOT EXISTS publish_jobs(id TEXT PRIMARY KEY, batch_id TEXT, platform TEXT,
              account_key TEXT, media_sha TEXT, state TEXT, snapshot TEXT, receipt TEXT DEFAULT '{}',
              message TEXT DEFAULT '', due REAL, created REAL, updated REAL, started REAL DEFAULT 0);
            CREATE UNIQUE INDEX IF NOT EXISTS publish_once ON publish_jobs(account_key,media_sha)
              WHERE state IN ('queued','running','paused','submitted','unknown');
            ''')
            if 'sau_origin' not in {r['name'] for r in db.execute('PRAGMA table_info(publish_media)')}:
                db.execute("ALTER TABLE publish_media ADD COLUMN sau_origin TEXT DEFAULT ''")

    def local_materials(self):
        return [{'id': 'local:' + r['id'], 'name': r['name'], 'size': r['size'], 'source': 'local',
                 'available': under(self.media, r['ref']).is_file(), '_path': str(under(self.media, r['ref'])),
                 '_sha': r['sha'], '_file': r['sau_ref'] if r['sau_origin'] == dumps(self.integration()) else '', **json.loads(r['info'])}
                for r in self.store.rows('SELECT * FROM publish_media ORDER BY created DESC')]

    def integration(self):
        settings = PublishingSettings(**{k: v for k, v in self.cfg.config.values.items() if k in PublishingSettings.model_fields})
        return {'url': settings.sau_url, 'root': str(Path(settings.sau_root).resolve())}

    def catalog(self, strict=False):
        error = ''
        try:
            source = self.bridge.catalog()
            connected = True
        except (ValueError, OSError) as ex:
            if strict:
                raise
            source = {'accounts': [], 'materials': []}
            error = str(ex)
            connected = False
        return {'connected': connected, 'message': error, 'accounts': source['accounts'],
                'materials': self.local_materials() + source['materials']}

    def state(self):
        catalog = self.catalog()
        return {**catalog, 'accounts': [public(a) for a in catalog['accounts']],
                'materials': [public(m) for m in catalog['materials']], 'batches': self.batches(),
                'platforms': [{'id': k, **v, 'draft': k == 'tencent'} for k, v in PLATFORMS.items()],
                'settings': PublishingSettings(**{k: v for k, v in self.cfg.config.values.items() if k in PublishingSettings.model_fields}).model_dump(),
                'worker': bool(self.thread and self.thread.is_alive())}

    async def upload(self, request, name):
        name = filename(name)
        suffix = Path(name).suffix.lower()
        if suffix not in ('.mp4', '.mov', '.m4v', '.webm', '.mkv', '.avi'):
            raise ValueError('请选择 MP4、MOV、M4V、WebM、MKV 或 AVI 视频')
        ident = uid()
        path = under(self.media, ident + suffix)
        size = 0
        try:
            with path.open('xb') as stream:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise ValueError('单个视频最多150MB')
                    stream.write(chunk)
            if size == 0:
                raise ValueError('不能上传空文件')
            # Media inspection is local; it never uploads to any platform.
            from starlette.concurrency import run_in_threadpool
            info = await run_in_threadpool(self.probe, path)
            digest = await run_in_threadpool(sha256, path)
            with self.store.connect(True) as db:
                existing = db.execute('SELECT id FROM publish_media WHERE sha=?', (digest,)).fetchone()
                if existing:
                    path.unlink()
                    return {'id': 'local:' + existing['id'], 'message': '相同视频已在素材库中'}
                db.execute('INSERT INTO publish_media(id,name,ref,size,sha,info,created) VALUES(?,?,?,?,?,?,?)',
                           (ident, name, path.name, size, digest, dumps(info), self.clock()))
            return {'id': 'local:' + ident, 'message': '视频已验证并保存到本地素材库'}
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def material(self, ident):
        if not ident.startswith('local:'):
            raise ValueError('仅本地上传素材提供此操作')
        rows = self.store.rows('SELECT * FROM publish_media WHERE id=?', (ident[6:],))
        if not rows:
            raise ValueError('素材不存在')
        return rows[0], under(self.media, rows[0]['ref'])

    def delete_material(self, ident):
        item, path = self.material(ident)
        with self.store.connect(True) as db:
            if db.execute("SELECT 1 FROM publish_jobs WHERE media_sha=? AND state IN ('queued','running','paused','unknown')", (item['sha'],)).fetchone():
                raise ValueError('该素材仍被发布任务使用，不能删除')
            for r in db.execute("SELECT payload FROM publish_batches WHERE state='draft'"):
                if ident in json.loads(r['payload'])['material_ids']:
                    raise ValueError('该素材仍被草稿使用，请先修改或删除草稿')
            path.unlink(missing_ok=True)
            db.execute('DELETE FROM publish_media WHERE id=?', (ident[6:],))
        return {'message': '本地素材已删除；已存在的发布记录保留'}

    def batches(self):
        result = []
        for row in self.store.rows('SELECT * FROM publish_batches ORDER BY created DESC,rowid DESC LIMIT 100'):
            payload = json.loads(row['payload'])
            jobs = self.store.rows('SELECT id,platform,state,message,due,created,updated,receipt,snapshot FROM publish_jobs WHERE batch_id=? ORDER BY created,id', (row['id'],))
            for job in jobs:
                snapshot = json.loads(job.pop('snapshot'))
                job.update(account_name=snapshot['account']['name'], material_name=snapshot['material']['name'], receipt=json.loads(job['receipt']))
            states = {j['state'] for j in jobs}
            state = ('running' if 'running' in states else 'queued' if 'queued' in states else
                     'unknown' if 'unknown' in states else 'paused' if 'paused' in states else
                     'failed' if 'failed' in states else 'submitted' if 'submitted' in states else
                     'cancelled' if jobs else row['state'])
            result.append({'id': row['id'], 'payload': payload, 'state': state, 'jobs': jobs,
                           'created': row['created'], 'updated': row['updated']})
        return result

    def save(self, payload, ident=None):
        data = payload.model_dump()
        if data['mode'] == 'scheduled' and data['schedule_at'] <= self.clock():
            raise ValueError('定时时间必须晚于当前时间')
        now = self.clock()
        with self.store.connect(True) as db:
            if ident:
                old = db.execute('SELECT * FROM publish_batches WHERE id=?', (ident,)).fetchone()
                if not old or old['state'] != 'draft':
                    raise ValueError('只有尚未启动的草稿可以编辑')
                if old['request_id'] != data['request_id']:
                    raise ValueError('草稿标识不一致，请重新打开')
                db.execute('UPDATE publish_batches SET payload=?,updated=? WHERE id=?', (dumps(data), now, ident))
            else:
                old = db.execute('SELECT * FROM publish_batches WHERE request_id=?', (data['request_id'],)).fetchone()
                if old:
                    if json.loads(old['payload']) != data:
                        raise ValueError('请求标识已用于其他内容，请重新新建')
                    return {'id': old['id'], 'message': '此草稿已经保存'}
                ident = uid()
                db.execute('INSERT INTO publish_batches(id,request_id,payload,created,updated) VALUES(?,?,?,?,?)',
                           (ident, data['request_id'], dumps(data), now, now))
        return {'id': ident, 'message': '发布草稿已保存，尚未加入执行队列'}

    def launch(self, ident):
        rows = self.store.rows('SELECT * FROM publish_batches WHERE id=?', (ident,))
        if not rows:
            raise ValueError('发布草稿不存在')
        if rows[0]['state'] != 'draft':
            return {'id': ident, 'message': '该任务已加入过队列，不会重复启动'}
        payload = json.loads(rows[0]['payload'])
        if payload['mode'] == 'scheduled' and payload['schedule_at'] <= self.clock():
            raise ValueError('定时时间已过，请编辑草稿后再执行')
        integration = self.integration()
        catalog = self.catalog(strict=True)
        accounts = {a['id']: a for a in catalog['accounts']}
        materials = {m['id']: m for m in catalog['materials']}
        selected_accounts, selected_materials = [], []
        for ident_a in payload['account_ids']:
            account = accounts.get(ident_a)
            if not account or account['status'] != 'recorded':
                raise ValueError('发布账号不存在或需要重新登录，请先到账号页处理')
            if payload['platform_draft'] and account['platform'] != 'tencent':
                raise ValueError('存入平台草稿仅支持视频号；其他平台可保存 JM 本地草稿')
            if payload['product_link'] and account['platform'] != 'dy':
                raise ValueError('商品链接仅支持抖音，请为其他平台单独创建任务')
            selected_accounts.append(account)
        for ident_m in payload['material_ids']:
            material = materials.get(ident_m)
            if not material or not material['available']:
                raise ValueError('素材不存在或原文件已被移动')
            path = Path(material['_path'])
            if not 0 < path.stat().st_size <= MAX_UPLOAD:
                raise ValueError('视频大小必须在150MB以内')
            info = self.probe(path)
            digest = sha256(path)
            if material.get('_sha') and material['_sha'] != digest:
                raise ValueError('本地视频内容已变动，请重新上传')
            selected_materials.append({**material, '_sha': digest, **info})
        if len(selected_accounts) * len(selected_materials) > 50:
            raise ValueError('单个批次最多50个视频与账号组合')
        if len({a['_key'] for a in selected_accounts}) != len(selected_accounts):
            raise ValueError('所选账号包含相同登录资料的重复记录，请只选择一个')
        if len({m['_sha'] for m in selected_materials}) != len(selected_materials):
            raise ValueError('所选素材包含相同视频的重复副本，请只选择一个')
        now, created = self.clock(), []
        with self.store.connect(True) as db:
            if self.integration() != integration:
                raise ValueError('预检过程中发布服务配置发生变化，请重新执行')
            row = db.execute('SELECT state FROM publish_batches WHERE id=?', (ident,)).fetchone()
            if row['state'] != 'draft':
                return {'id': ident, 'message': '该任务已加入队列'}
            for account in selected_accounts:
                if db.execute('SELECT 1 FROM risk WHERE platform=?', (account['platform'],)).fetchone():
                    raise ValueError('所选平台存在暂停记录，请先处理运行异常')
                for material in selected_materials:
                    if db.execute("SELECT 1 FROM publish_jobs WHERE account_key=? AND media_sha=? AND state IN ('queued','running','paused','submitted','unknown')", (account['_key'], material['_sha'])).fetchone():
                        raise ValueError('该账号已有相同视频的执行记录或队列，已阻止重复发布')
                    job_id = uid()
                    snapshot = {'account': account, 'material': material, 'content': payload,
                                'revision': self.cfg.code_revision, 'integration': integration}
                    due = payload['schedule_at'] if payload['mode'] == 'scheduled' else now
                    db.execute('INSERT INTO publish_jobs(id,batch_id,platform,account_key,media_sha,state,snapshot,due,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)',
                               (job_id, ident, account['platform'], account['_key'], material['_sha'], 'queued', dumps(snapshot), due, now, now))
                    created.append(job_id)
            db.execute("UPDATE publish_batches SET state='queued',updated=? WHERE id=?", (now, ident))
        return {'id': ident, 'created': created, 'message': f'已加入{len(created)}个发布组合；按时间与平台间隔依次执行'}

    def control(self, ident, action):
        if action not in ('pause', 'resume', 'cancel'):
            raise ValueError('操作无效')
        with self.store.connect(True) as db:
            if not db.execute('SELECT 1 FROM publish_batches WHERE id=?', (ident,)).fetchone():
                raise ValueError('发布任务不存在')
            if action == 'resume':
                if db.execute("SELECT 1 FROM publish_jobs WHERE batch_id=? AND state='unknown'", (ident,)).fetchone():
                    raise ValueError('仍有不确定的提交结果，不允许重新执行；先核对平台记录')
                db.execute("UPDATE publish_jobs SET state='queued',updated=? WHERE batch_id=? AND state='paused'", (self.clock(), ident))
            else:
                target = 'paused' if action == 'pause' else 'cancelled'
                db.execute("UPDATE publish_jobs SET state=?,updated=?,message=? WHERE batch_id=? AND state IN ('queued','paused')",
                           (target, self.clock(), '用户停止后续执行', ident))
                db.execute("UPDATE publish_batches SET state=?,updated=? WHERE id=? AND state='draft'", (target, self.clock(), ident))
        return {'message': '已继续排队' if action == 'resume' else '已停止后续组合；已经提交中的请求仍将记录实际结果'}

    def recover(self):
        uncertain = self.store.rows("SELECT id,platform FROM publish_jobs WHERE state='running'")
        for job in uncertain:
            self._finish(job['id'], 'unknown', '服务中断，发布结果不明；禁止自动重发')
            self.store.lock(job['platform'], '内容发布中断，需核对平台结果后再处理')

    def resolve(self, ident, outcome, note):
        """An explicit exception record, never an automatic retry or unlock."""
        if outcome not in ('submitted', 'not_sent') or len(note.strip()) < 12:
            raise ValueError('请填写平台核对结果和至少12字的说明')
        with self.store.connect(True) as db:
            row = db.execute('SELECT * FROM publish_jobs WHERE id=?', (ident,)).fetchone()
            if not row or row['state'] != 'unknown':
                raise ValueError('只有结果不明的任务需要核对记录')
            receipt = {'status': outcome, 'verification': 'user_record', 'note': note,
                       'visibility': 'user_confirmed' if outcome == 'submitted' else 'not_sent'}
            db.execute('UPDATE publish_jobs SET state=?,receipt=?,message=?,updated=? WHERE id=?',
                       ('submitted' if outcome == 'submitted' else 'failed', dumps(receipt),
                        '用户已记录平台核对结果；未自动重试或解除限制', self.clock(), ident))
        self.store.event('用户核对内容发布结果：' + note, ident)
        return {'message': '核对结果已记录。平台保持暂停，可到运行记录处理限制；不会自动重发。'}

    def start(self):
        self.recover()
        self.thread = threading.Thread(target=self.loop, name='jm-publishing', daemon=True)
        self.thread.start()

    def close(self):
        self.shutdown.set()
        if self.thread:
            self.thread.join(timeout=5)

    def loop(self):
        while not self.shutdown.is_set():
            try:
                self.tick()
            except Exception:
                self.store.event('内容发布检查未完成，执行器将在下一轮检查连接', level='error')
            self.shutdown.wait(3)

    def _finish(self, ident, state, message, receipt=None):
        with self.store.connect(True) as db:
            db.execute('UPDATE publish_jobs SET state=?,message=?,receipt=?,updated=? WHERE id=?',
                       (state, message, dumps(receipt or {}), self.clock(), ident))

    def tick(self):
        if not self.step_lock.acquire(False):
            return False
        try:
            if self.shutdown.is_set() or revision() != self.cfg.code_revision:
                return False
            rows = self.store.rows("SELECT * FROM publish_jobs WHERE state='queued' AND due<=? ORDER BY due,created,id LIMIT 1", (self.clock(),))
            if not rows:
                return False
            job = rows[0]
            snapshot = json.loads(job['snapshot'])
            if snapshot['revision'] != self.cfg.code_revision:
                self._finish(job['id'], 'paused', '程序版本已更新，请检查这项发布任务')
                return False
            if snapshot.get('integration') != self.integration():
                self._finish(job['id'], 'paused', '发布服务配置已变动；请使用当前配置新建任务，原任务未发送')
                return False
            if self.store.rows('SELECT 1 FROM risk WHERE platform=?', (job['platform'],)):
                self._finish(job['id'], 'paused', '平台暂停记录尚未处理')
                return False
            settings = PublishingSettings(**{k: v for k, v in self.cfg.config.values.items() if k in PublishingSettings.model_fields})
            recent = self.store.rows("SELECT started FROM publish_jobs WHERE platform=? AND started>? AND state IN ('running','submitted','unknown') ORDER BY started DESC", (job['platform'], self.clock()-86400))
            due = max(self.clock(), (recent[0]['started'] + settings.publish_gap_minutes*60) if recent else 0)
            if len(recent) >= settings.publish_daily_limit:
                due = max(due, recent[settings.publish_daily_limit-1]['started'] + 86400)
            if due > self.clock():
                with self.store.connect() as db:
                    db.execute("UPDATE publish_jobs SET due=?,message='等待平台发布间隔或24小时限额' WHERE id=? AND state='queued'", (due, job['id']))
                return False
            # A down service is checked before reserving a send. No submit is retried.
            try:
                catalog = self.catalog(strict=True)
            except SAUUnavailable:
                with self.store.connect() as db:
                    db.execute("UPDATE publish_jobs SET due=?,message='等待内容发布服务恢复' WHERE id=? AND state='queued'", (self.clock()+30, job['id']))
                return False
            account = next((a for a in catalog['accounts'] if a['id'] == snapshot['account']['id']), None)
            if not account or account['_key'] != snapshot['account']['_key'] or account['name'] != snapshot['account']['name'] or account['status'] != 'recorded':
                self._finish(job['id'], 'paused', '发布账号已变动或需要重新登录，未发送')
                return False
            material = snapshot['material']
            path = Path(material['_path'])
            try:
                if not path.is_file() or sha256(path) != material['_sha']:
                    raise ValueError()
            except (ValueError, OSError):
                self._finish(job['id'], 'failed', '视频原文件缺失或内容变动，未发送')
                return False
            with self.cfg.browser_lock:
                if self.shutdown.is_set():
                    return False
                with self.store.connect(True) as db:
                    current = db.execute('SELECT state FROM publish_jobs WHERE id=?', (job['id'],)).fetchone()
                    if current['state'] != 'queued' or db.execute('SELECT 1 FROM risk WHERE platform=?', (job['platform'],)).fetchone():
                        return False
                    db.execute("UPDATE publish_jobs SET state='running',updated=?,message='正在准备提交' WHERE id=?", (self.clock(), job['id']))
                # Upload failures occur before the publish call and are distinguishable.
                try:
                    ref = material['_file']
                    if not ref and material['id'].startswith('local:'):
                        saved = self.store.rows('SELECT sau_ref,sau_origin FROM publish_media WHERE id=?', (material['id'][6:],))
                        ref = saved[0]['sau_ref'] if saved and saved[0]['sau_origin'] == dumps(snapshot['integration']) else ''
                    if not ref:
                        ref = self.bridge.upload(path)
                        if material['id'].startswith('local:'):
                            with self.store.connect() as db:
                                db.execute('UPDATE publish_media SET sau_ref=?,sau_origin=? WHERE id=?', (ref, dumps(snapshot['integration']), material['id'][6:]))
                    if self.shutdown.is_set():
                        self._finish(job['id'], 'paused', '服务正在关闭，尚未调用发布')
                        return False
                except Exception:
                    self._finish(job['id'], 'failed', '素材准备失败，尚未调用发布；请检查服务与原视频')
                    return False
                with self.store.connect() as db:
                    db.execute("UPDATE publish_jobs SET started=?,message='已调用发布，请等待结果' WHERE id=?", (self.clock(), job['id']))
                try:
                    receipt = self.bridge.publish(account, ref, snapshot['content'])
                    if not isinstance(receipt, dict) or receipt.get('status') != 'submitted':
                        raise ValueError('没有明确的提交回执')
                    self._finish(job['id'], 'submitted', receipt['message'], receipt)
                except Exception:
                    self._finish(job['id'], 'unknown', '发布请求未获得确定回执，禁止自动重发；请核对平台作品记录')
                    self.store.lock(job['platform'], '内容发布结果不确定，暂停该平台后续操作')
                return True
        finally:
            self.step_lock.release()
