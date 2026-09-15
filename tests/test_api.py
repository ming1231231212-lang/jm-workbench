from fastapi.testclient import TestClient
import pytest
from jm_workbench.web.app import create_app

@pytest.fixture
def api(tmp_path):
    app = create_app(tmp_path, worker=False)
    with TestClient(app, base_url='http://127.0.0.1:8776') as client:
        token = client.get('/api/state').json()['token']
        client.headers.update({'X-JM-Token': token, 'Origin': 'http://127.0.0.1:8776'})
        yield client, app.state.cfg

def test_brand_and_assets(api):
    client, _ = api
    assert client.get('/api/health').json()['name'] == 'JM工作台'
    assert client.get('/api/health').json()['app_id'] == 'jm-workbench'
    assert 'charset=utf-8' in client.get('/api/health').headers['Content-Type']
    assert '<title>JM工作台</title>' in client.get('/').text
    for asset in ('app.js', 'views.js', 'ui.js', 'style.css', 'data-page.js', 'data-page.css'):
        assert client.get('/static/'+asset).status_code == 200

def test_cross_origin_and_missing_token_rejected(api):
    client, _ = api
    assert client.post('/api/stop', json={}, headers={'Origin':'https://outside.example'}).status_code == 403
    assert client.post('/api/stop', json={}, headers={'X-JM-Token':''}).status_code == 403
    assert client.get('/api/state', headers={'Host':'outside.example'}).status_code == 403
    assert client.get('/').headers['Content-Security-Policy'].endswith("form-action 'self'")

def test_account_task_matrix_config_roundtrip(api, monkeypatch):
    client, cfg = api
    monkeypatch.setattr('jm_workbench.services.configuration.endpoint', lambda _: 'ws://127.0.0.1:1234/test')
    monkeypatch.setattr(cfg.config, 'crawler_ready', lambda: True)
    account = client.post('/api/accounts', json={'name':'快手一号','platform':'ks'}).json()
    task = client.post('/api/tasks', json={'name':'采集测试','platform':'ks','kind':'crawler','keywords':['明确关键词']}).json()
    assert client.post('/api/matrix', json={'task_id':task['id'],'account_id':account['id']}).status_code == 200
    assert client.post('/api/launch', json={}).json()['ok'] is False
    cfg.store.put('account', dict(account, connection='connected'), account['id'])
    launch = client.post('/api/launch', json={}).json()
    assert len(launch['created']) == 1
    assert client.post('/api/launch', json={}).json()['existing'] == launch['created']
    assert client.post('/api/stop', json={}).status_code == 200
    assert client.get('/api/state').json()['runs'][0]['state'] == 'paused'

def test_invalid_payload_friendly_error(api):
    client, _ = api
    result=client.post('/api/tasks', json={'name':'抖音发布','platform':'dy','kind':'adult_comments','keywords':['x']})
    assert result.status_code == 422 and '仅支持爬虫' in result.json()['error']
    result=client.post('/api/accounts', json={'name':'x','platform':'ks','password':'never-store'})
    assert result.status_code == 422

def test_data_filter_export_and_formula_safety(api):
    client, cfg = api
    cfg.store.add_evidence('r','ks',{'caption':'=HYPERLINK("bad")','video_id':'123'},'skipped','缺少证据')
    cfg.store.add_evidence('r','dy',{'caption':'其他内容'},'collected','只采集')
    assert client.get('/api/data?q=HYPERLINK').json()['total']==1
    assert client.get('/api/data?decision=collected').json()['total']==1
    assert "'=HYPERLINK" in client.get('/api/export').text

def test_unknown_send_cannot_clear_risk(api):
    client,cfg=api
    cfg.store.lock('ks','结果不确定')
    with cfg.store.connect() as db:
        db.execute("INSERT INTO attempts(id,platform,video_id,state,created) VALUES('x','ks','v','unknown',1)")
    result=client.post('/api/risk/ks/clear',json={'note':'我已经完成平台问题处理并检查浏览器'})
    assert result.status_code==400
    assert cfg.store.rows('SELECT * FROM risk')


def test_comment_scope_and_core_roundtrip_and_read_only_preview(api):
    from jm_workbench.policies.comments import ADULT_CORE
    client,cfg=api
    payload=dict(name='成人商家',platform='ks',kind='adult_comments',keywords=['成人用品店'],
                 adult_target='merchant',comment_mode='core_variants',comment_core=ADULT_CORE)
    preview=client.post('/api/comment-preview',json=payload)
    assert preview.status_code==200 and len(preview.json()['examples'])==3
    assert cfg.store.objects('task')==[] and cfg.store.rows('SELECT * FROM attempts')==[]
    created=client.post('/api/tasks',json=payload).json()
    assert created['comment_core']==ADULT_CORE and created['adult_target']=='merchant'
    changed=client.put('/api/tasks/'+created['id'],json=dict(payload,adult_target='inventory')).json()
    assert changed['adult_target']=='inventory' and changed['version']==2
    assert client.post('/api/comment-preview',json=dict(payload,kind='peiwang_comments')).status_code==422
