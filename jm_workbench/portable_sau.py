"""Clean, loopback-only SAU companion with a small account manager."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import threading
import time

from .portable import BUNDLE, browser_path


def initialize(home):
    root = home / 'video-publisher'
    for folder in ('db', 'cookiesFile', 'videoFile', 'logs'):
        (root / folder).mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(root / 'db/database.db') as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS user_info (
          id INTEGER PRIMARY KEY AUTOINCREMENT, type INTEGER NOT NULL, filePath TEXT NOT NULL,
          userName TEXT NOT NULL, status INTEGER DEFAULT 0);
          CREATE TABLE IF NOT EXISTS file_records (id INTEGER PRIMARY KEY AUTOINCREMENT,
          filename TEXT NOT NULL, filesize REAL, upload_time DATETIME DEFAULT CURRENT_TIMESTAMP, file_path TEXT);''')
    return root


def create_connector(home, port):
    from flask import request, jsonify, Response, send_from_directory
    import types
    root = initialize(home)
    vendor = BUNDLE / 'vendor/sau'
    conf = types.ModuleType('conf')
    conf.BASE_DIR = root
    conf.LOCAL_CHROME_PATH = str(browser_path())
    conf.LOCAL_CHROME_HEADLESS = False
    conf.DEBUG_MODE = False
    conf.XHS_SERVER = 'http://127.0.0.1:11901'
    conf.YT_PROXY = None
    sys.modules['conf'] = conf
    sys.path.insert(0, str(vendor))
    import sau_backend
    app = sau_backend.app
    # Remove the upstream wildcard CORS hook. This service only accepts local JM requests.
    app.after_request_funcs.clear()
    token = os.environ['JM_SAU_TOKEN']
    origin = f'http://127.0.0.1:{port}'
    allowed = {'/', '/manager.js', '/manager.css', '/getAccounts', '/getValidAccounts', '/getFiles',
               '/login', '/deleteAccount', '/updateUserinfo', '/jmGuard', '/uploadSave', '/postVideo'}

    @app.before_request
    def guard():
        if request.host != f'127.0.0.1:{port}' or request.remote_addr != '127.0.0.1':
            return jsonify(error='仅支持本机访问'), 403
        if request.path not in allowed:
            return jsonify(error='请通过 JM工作台进行此操作'), 404
        if request.headers.get('origin') not in (None, origin) or request.headers.get('sec-fetch-site') == 'cross-site':
            return jsonify(error='请求来源无效'), 403
        if request.path not in ('/', '/manager.js', '/manager.css'):
            supplied = request.headers.get('X-JM-Connector-Token', '')
            if request.path == '/login':
                supplied = request.args.get('token', '')
            if not secrets.compare_digest(token, supplied):
                return jsonify(error='请从工作台重新打开账号管理'), 403
        if request.path == '/login':
            if request.args.get('type') not in ('1', '2', '3', '4') or not 1 <= len(request.args.get('id', '')) <= 60:
                return jsonify(error='请选择平台并填写账号名称'), 400
        if request.path == '/postVideo':
            data = request.get_json(silent=True) or {}
            if data.get('jmGuarded') is not True or data.get('enableTimer') is not False:
                return jsonify(error='只允许工作台已确认的单次任务'), 400
            from .publishing.sau import under
            try:
                for key, folder in (('fileList', 'videoFile'), ('accountList', 'cookiesFile')):
                    items = data[key]
                    if not isinstance(items, list) or len(items) != 1 or not under(root / folder, items[0]).is_file():
                        raise ValueError()
            except (KeyError, ValueError, TypeError):
                return jsonify(error='账号或素材无效'), 400
        if request.path in ('/deleteAccount', '/updateUserinfo'):
            ident = request.args.get('id') if request.path == '/deleteAccount' else (request.get_json(silent=True) or {}).get('id')
            with sqlite3.connect(root / 'db/database.db') as db:
                row = db.execute('SELECT type,filePath FROM user_info WHERE id=?', (ident,)).fetchone()
            if request.path == '/updateUserinfo':
                data = request.get_json(silent=True) or {}
                if not row or data.get('type') != row[0] or not isinstance(data.get('userName'), str) or not 1 <= len(data['userName'].strip()) <= 60:
                    return jsonify(code=400, msg='只能修改已有账号的备注，不能变更账号平台', data=None), 400
            if row and (home / 'jm.db').is_file():
                platform = {1:'xhs', 2:'tencent', 3:'dy', 4:'ks'}.get(row[0], '')
                key = hashlib.sha256(f'{platform}:{row[1]}'.encode()).hexdigest()
                with sqlite3.connect(home / 'jm.db') as db:
                    busy = db.execute("SELECT 1 FROM publish_jobs WHERE account_key=? AND state IN ('queued','running','paused','unknown')", (key,)).fetchone()
                if busy:
                    return jsonify(code=400, msg='账号还有未结束的发布任务，请先在工作台处理', data=None), 400

    @app.after_request
    def headers(response):
        for key in list(response.headers):
            if key[0].lower().startswith('access-control-'):
                del response.headers[key[0]]
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    def index():
        text = (BUNDLE / 'app/jm_workbench/web/portable/manager.html').read_text(encoding='utf-8')
        return Response(text.replace('__CONNECTOR_TOKEN__', token), mimetype='text/html')
    app.view_functions['index'] = index
    @app.route('/manager.js')
    def manager_js():
        return send_from_directory(BUNDLE / 'app/jm_workbench/web/portable', 'manager.js')
    @app.route('/manager.css')
    def manager_css():
        return send_from_directory(BUNDLE / 'app/jm_workbench/web/portable', 'manager.css')
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    from werkzeug.serving import make_server
    app = create_connector(args.home, args.port)
    server = make_server('127.0.0.1', args.port, app, threaded=True)
    def stop():
        while not (args.home / 'portable-stop').exists():
            time.sleep(.5)
        server.shutdown()
    threading.Thread(target=stop, daemon=True).start()
    server.serve_forever()


if __name__ == '__main__':
    main()
