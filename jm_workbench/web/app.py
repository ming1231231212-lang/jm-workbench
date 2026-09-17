import csv
import io
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from .. import APP_NAME, __version__
from ..core.config import Config, revision
from ..core.db import Store
from ..core.models import AccountInput, TaskInput, BindingInput, SettingsInput, LaunchInput, ClearRiskInput
from ..core.platforms import PLATFORMS
from ..services.configuration import Configuration
from ..services.engine import Engine
from ..services.data_view import data_view
from ..services.continuation import continue_pending
from ..adapters.errors import LocalBrowserError, PlatformRisk
from ..policies.rules import DEFAULTS
from ..policies.comments import examples, target_description, ADULT_CORE


def create_app(home=None, worker=True, configuration=None):
    config = Config(home)
    store = Store(config.home/'jm.db')
    cfg = configuration or Configuration(config, store)
    config, store = cfg.config, cfg.store
    engine, token = Engine(cfg), secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        if worker:
            engine.start()
        yield
        engine.close()

    app = FastAPI(title=APP_NAME, version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.cfg, app.state.engine = cfg, engine

    @app.middleware('http')
    async def local_only(request, call_next):
        host = request.headers.get('host', '')
        parsed = urlparse('http://' + host)
        if parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.username or parsed.password:
            return JSONResponse({'error': '工作台仅接受本机访问'}, status_code=403)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if (origin and origin != 'http://' + host) or not secrets.compare_digest(request.headers.get('x-jm-token', ''), token):
                return JSONResponse({'error': '请求来源无效，请刷新工作台后重试'}, status_code=403)
            if revision() != cfg.code_revision:
                return JSONResponse({'error': '代码已更新，请重新启动工作台加载新版本'}, status_code=409)
            if len(await request.body()) > 32768:
                return JSONResponse({'error': '配置过大'}, status_code=413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['Cache-Control'] = 'no-store'
        if response.headers.get('content-type', '').startswith('application/json'):
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response

    @app.exception_handler(ValueError)
    @app.exception_handler(LocalBrowserError)
    @app.exception_handler(PlatformRisk)
    async def friendly_error(request, ex):
        return JSONResponse({'error': str(ex)}, status_code=400)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, ex):
        return JSONResponse({'error': '；'.join(str(e['msg']).replace('Value error, ', '') for e in ex.errors())}, status_code=422)

    @app.get('/api/health')
    def health():
        return {'app_id': 'jm-workbench', 'name': APP_NAME, 'version': __version__, 'revision': cfg.code_revision, 'worker': worker}

    @app.get('/api/state')
    def state():
        runs = store.rows('SELECT * FROM runs ORDER BY created DESC LIMIT 100')
        for row in runs:
            row['snapshot'] = json.loads(row['snapshot'])
            row['progress'] = json.loads(row['progress'])
        continuations = {r['source_run_id']: r['run_id'] for r in store.rows('SELECT * FROM continuations')}
        for row in runs:
            row['continuation_id'] = continuations.get(row['id'])
        counts = {r['decision']: r['n'] for r in store.rows('SELECT decision,COUNT(*) n FROM evidence GROUP BY decision')}
        attempts = {r['state']: r['n'] for r in store.rows('SELECT state,COUNT(*) n FROM attempts GROUP BY state')}
        return {'name': APP_NAME, 'version': __version__, 'revision': cfg.code_revision, 'token': token,
                'accounts': store.objects('account'), 'tasks': store.objects('task'), 'bindings': store.objects('binding'),
                'runs': runs, 'risk': store.rows('SELECT * FROM risk'), 'counts': counts, 'attempt_counts': attempts,
                'history_count': store.rows('SELECT COUNT(*) n FROM history')[0]['n'],
                'platforms': [{'id': k, **v, 'crawler': k == 'ks' or config.crawler_ready(), 'verification': '待该平台登录实测'} for k, v in PLATFORMS.items()],
                'settings': config.values, 'defaults': DEFAULTS, 'adult_comment_core': ADULT_CORE,
                'events': store.rows('SELECT * FROM events ORDER BY id DESC LIMIT 50')}

    @app.post('/api/accounts')
    def add_account(payload: AccountInput):
        return cfg.account(payload.model_dump())

    @app.put('/api/accounts/{ident}')
    def edit_account(ident: str, payload: AccountInput):
        store.get('account', ident)
        return cfg.account(payload.model_dump(), ident)

    @app.post('/api/accounts/{ident}/open')
    def account_open(ident: str):
        return cfg.open_account(ident)

    @app.post('/api/accounts/{ident}/check')
    def account_check(ident: str):
        return cfg.check_account(ident)

    @app.post('/api/tasks')
    def add_task(payload: TaskInput):
        return cfg.task(payload.model_dump())

    @app.post('/api/comment-preview')
    def comment_preview(payload: TaskInput):
        task = payload.model_dump()
        return {'examples': examples(task), 'target_description': target_description(task),
                'mode': task['comment_mode']}

    @app.put('/api/tasks/{ident}')
    def edit_task(ident: str, payload: TaskInput):
        store.get('task', ident)
        return cfg.task(payload.model_dump(), ident)

    @app.post('/api/matrix')
    def bind(payload: BindingInput):
        return cfg.binding(payload.model_dump())

    @app.post('/api/launch')
    def launch(payload: LaunchInput):
        return cfg.launch(payload.task_id)

    @app.post('/api/stop')
    def stop():
        store.stop()
        return {'message': '已停止任务；进行中的请求结束后不会执行下一步'}

    @app.post('/api/runs/{ident}/stop')
    def stop_one(ident: str):
        store.stop(ident)
        return {'message': '已停止此任务'}

    @app.post('/api/runs/{ident}/continue')
    def continue_run(ident: str):
        return continue_pending(cfg, ident)

    @app.put('/api/settings')
    def settings(payload: SettingsInput):
        if store.rows("SELECT 1 FROM runs WHERE state IN ('queued','running','waiting')"):
            raise ValueError('请先停止活动任务再修改运行设置')
        config.save(payload.model_dump())
        store.event('运行路径已更新')
        return {'message': '运行设置已保存'}

    @app.post('/api/risk/{platform}/clear')
    def clear_risk(platform: str, payload: ClearRiskInput):
        if store.rows("SELECT 1 FROM attempts WHERE platform=? AND state IN ('reserved','unknown')", (platform,)):
            raise ValueError('仍有未确认的发送结果，不能解除；请核实发送记录后处理')
        with store.connect(True) as db:
            db.execute('DELETE FROM risk WHERE platform=?', (platform,))
        store.event('用户确认平台问题已处理：' + payload.note)
        return {'message': '限制记录已解除，任务保持停止；可重新一键执行'}

    @app.get('/api/data')
    def data(q: str = '', decision: str = '', page: int = 1, batch: str = 'all', category: str = ''):
        return data_view(store, q=q[:200], decision=decision, page=page, batch=batch, category=category)

    @app.get('/api/attempts')
    def attempts():
        rows = store.rows('SELECT * FROM attempts ORDER BY created DESC LIMIT 100')
        for row in rows:
            row['evidence'] = json.loads(row['evidence'] or '{}')
            row['receipt'] = json.loads(row['receipt'])
        return rows

    @app.get('/api/export')
    def export():
        content = io.StringIO(newline='')
        writer = csv.writer(content)
        writer.writerow(['平台','视频ID','作者ID','正文','执行判断','原因','时间','业务分类','分类说明'])
        from ..services.data_view import classify, CATEGORIES
        for row in store.rows('SELECT * FROM evidence ORDER BY id'):
            item = json.loads(row['data'])
            category, reason = classify(item)
            cells = [row['platform'], row['video_id'], row['author_id'], item.get('caption', item.get('title', item.get('content',''))), row['decision'], row['reason'], row['created'], CATEGORIES[category], reason]
            writer.writerow(["'"+str(v) if str(v).lstrip().startswith(('=','+','-','@','\t','\r')) else v for v in cells])
        return Response('\ufeff'+content.getvalue(), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename="jm-data.csv"'})

    static = Path(__file__).parent/'static'
    app.mount('/static', StaticFiles(directory=static), name='static')

    @app.get('/')
    def index():
        return FileResponse(static/'index.html')

    return app
