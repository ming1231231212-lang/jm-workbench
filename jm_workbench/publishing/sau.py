"""Narrow loopback-only SAU adapter. Never expose cookie paths in public responses."""
import hashlib
import http.client
import json
import os
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from urllib.parse import urlparse
from .models import PLATFORMS, PublishingSettings, MAX_UPLOAD


class SAUUnavailable(ValueError):
    pass


def filename(value):
    value = str(value)
    if not value or len(value) > 240 or value in ('.', '..') or any(c in value for c in '/\\:\x00\r\n'):
        raise ValueError('素材或账号引用不安全')
    return value


def under(root, name):
    root = Path(root).resolve()
    target = (root / filename(name)).resolve()
    if not target.is_relative_to(root):
        raise ValueError('引用超出允许目录')
    return target


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


class SAUBridge:
    def __init__(self, config):
        self.config = config
        self.start_lock = threading.Lock()

    def settings(self):
        keys = PublishingSettings.model_fields
        return PublishingSettings(**{k: v for k, v in self.config.values.items() if k in keys})

    def _connection(self, timeout):
        return http.client.HTTPConnection('127.0.0.1', urlparse(self.settings().sau_url).port, timeout=timeout)

    @staticmethod
    def _response(conn):
        r = conn.getresponse()
        raw = r.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024 or r.status != 200:
            raise SAUUnavailable('发布服务未完成请求，请检查服务状态和运行记录')
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise SAUUnavailable('发布服务返回格式异常')
        if not isinstance(result, dict) or result.get('code') != 200:
            raise SAUUnavailable('发布服务返回失败，请检查账号与素材')
        return result.get('data')

    def request(self, path, body=None, timeout=5):
        conn = self._connection(timeout)
        try:
            conn.request('GET' if body is None else 'POST', path,
                         body=None if body is None else json.dumps(body).encode(),
                         headers={'Content-Type': 'application/json'})
            return self._response(conn)
        except (OSError, http.client.HTTPException) as ex:
            raise SAUUnavailable('内容发布服务未连接，请在设置中启动或检查 SAU') from ex
        finally:
            conn.close()

    def catalog(self):
        guard = self.request('/jmGuard')
        if not isinstance(guard, dict) or guard.get('version') != 1 or guard.get('single_submit') is not True:
            raise SAUUnavailable('SAU 缺少 JM 防重复提交保护，请先安装接入补丁并重启发布服务')
        raw_accounts, raw_materials = self.request('/getAccounts'), self.request('/getFiles')
        if not isinstance(raw_accounts, list) or not isinstance(raw_materials, list):
            raise SAUUnavailable('发布服务的账号或素材格式不兼容')
        types = {v['type']: k for k, v in PLATFORMS.items()}
        accounts = []
        for row in raw_accounts:
            if not isinstance(row, list) or len(row) < 5 or row[1] not in types:
                continue
            ref = filename(row[2])
            platform = types[row[1]]
            accounts.append({'id': f'sau:{int(row[0])}', 'name': str(row[3])[:80], 'platform': platform,
                             'status': 'recorded' if row[4] == 1 else 'needs_login',
                             '_file': ref, '_key': hashlib.sha256(f'{platform}:{ref}'.encode()).hexdigest()})
        materials = []
        for row in raw_materials:
            if not isinstance(row, dict):
                continue
            try:
                ref = filename(row['file_path'])
                path = under(Path(self.settings().sau_root) / 'videoFile', ref)
                materials.append({'id': f'sau:{int(row["id"])}', 'name': str(row['filename'])[:200],
                                  'size': path.stat().st_size if path.is_file() else 0,
                                  'source': 'sau', 'available': path.is_file(), '_file': ref, '_path': str(path)})
            except (ValueError, KeyError, OSError):
                continue
        return {'accounts': accounts, 'materials': materials}

    def upload(self, path):
        path = Path(path)
        boundary = 'jm' + uuid.uuid4().hex
        head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n').encode()
        tail = f'\r\n--{boundary}--\r\n'.encode()
        if not 0 < path.stat().st_size <= MAX_UPLOAD:
            raise ValueError('视频文件大小无效')
        conn = self._connection(120)
        try:
            conn.putrequest('POST', '/uploadSave')
            conn.putheader('Content-Type', f'multipart/form-data; boundary={boundary}')
            conn.putheader('Content-Length', str(len(head) + path.stat().st_size + len(tail)))
            conn.endheaders()
            conn.send(head)
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    conn.send(block)
            conn.send(tail)
            result = self._response(conn)
            return filename(result['filepath'])
        except (OSError, http.client.HTTPException, KeyError, TypeError) as ex:
            raise SAUUnavailable('素材传入发布服务失败，尚未调用发布接口') from ex
        finally:
            conn.close()

    def publish(self, account, material_ref, content):
        self.request('/postVideo', {
            'type': PLATFORMS[account['platform']]['type'], 'fileList': [filename(material_ref)],
            'accountList': [filename(account['_file'])], 'title': content['title'], 'tags': content['tags'],
            'category': 0, 'enableTimer': False, 'jmGuarded': True,
            'videosPerDay': 1, 'dailyTimes': [], 'startDays': 0,
            'isDraft': content['platform_draft'], 'productLink': content['product_link'],
            'productTitle': content['product_title'], 'thumbnail': '',
        }, timeout=900)
        return {'status': 'submitted', 'message': 'SAU 已返回提交完成；作品可见性未核验', 'visibility': 'unverified'}

    def start(self):
        with self.start_lock:
            return self._start()

    def _start(self):
        """Start installed services only; no database initialization or publishing."""
        import socket
        if os.name != 'nt':
            raise ValueError('自动启动仅支持本机 Windows 安装')
        settings = self.settings()
        root = Path(settings.sau_root).resolve()
        python = root / '.venv' / 'Scripts' / 'python.exe'
        if not python.is_file() or not (root / 'sau_backend.py').is_file() or not (root / 'db' / 'database.db').is_file():
            raise ValueError('SAU 安装目录或现有数据库不完整')
        port = urlparse(settings.sau_url).port
        def listening(port):
            with socket.socket() as sock:
                sock.settimeout(1)
                return sock.connect_ex(('127.0.0.1', port)) == 0
        backend_running = listening(port)
        if backend_running:
            self.catalog()  # A different port owner is never terminated or replaced.
        web_port = urlparse(settings.sau_web_url).port
        web_running = listening(web_port)
        if web_running:
            connection = http.client.HTTPConnection('127.0.0.1', web_port, timeout=3)
            try:
                connection.request('GET', '/')
                response = connection.getresponse()
                if response.status != 200 or b'SAU' not in response.read(65536):
                    raise ValueError('账号管理页面端口被其他服务占用，请检查接入配置')
            finally:
                connection.close()
        node = shutil.which('node')
        vite = root / 'sau_frontend/node_modules/vite/bin/vite.js'
        if not web_running and (not node or not vite.is_file()):
            raise ValueError('SAU 账号管理页面缺少 Node 或已安装的前端依赖')
        log = self.config.home / 'publishing-service.log'
        with log.open('ab') as stream:
            if not backend_running:
                subprocess.Popen([str(python), '-m', 'flask', '--app', 'sau_backend', 'run', '--host', '127.0.0.1', '--port', str(port)],
                                 cwd=root, stdout=stream, stderr=stream, creationflags=subprocess.CREATE_NO_WINDOW)
            if not web_running:
                subprocess.Popen([node, str(vite), '--host', '127.0.0.1', '--port', str(web_port), '--strictPort'],
                                 cwd=root / 'sau_frontend', env={**os.environ, 'BROWSER': 'none'},
                                 stdout=stream, stderr=stream, creationflags=subprocess.CREATE_NO_WINDOW)
        return {'message': '已检查运行状态并启动缺少的服务；请稍后刷新连接'}
