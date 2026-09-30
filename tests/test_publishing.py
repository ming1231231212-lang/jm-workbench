import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from jm_workbench.web.app import create_app
from jm_workbench.publishing.models import PublishInput, PublishingSettings, MAX_UPLOAD
from jm_workbench.publishing.sau import SAUUnavailable, filename, under
from jm_workbench.publishing.service import Publishing, probe_video


class FakeSAU:
    def __init__(self, path):
        self.path = path
        self.accounts = [{'id':'sau:1','name':'Test account','platform':'ks','status':'recorded','_file':'private-cookie.json','_key':'identity-one'}]
        self.materials = [{'id':'sau:10','name':'sample.mp4','size':path.stat().st_size,'source':'sau','available':True,'_file':'sample.mp4','_path':str(path)}]
        self.sent, self.uploads, self.fail, self.offline = [], [], False, False
        self.entered = None
        self.release = None

    def catalog(self):
        if self.offline:
            raise SAUUnavailable('服务未连接')
        return copy.deepcopy({'accounts':self.accounts,'materials':self.materials})

    def upload(self, path):
        self.uploads.append(str(path))
        return 'uploaded.mp4'

    def publish(self, account, material, content):
        self.sent.append((account['id'],material,copy.deepcopy(content)))
        if self.entered:
            self.entered.set()
            assert self.release.wait(5)
        if self.fail:
            raise TimeoutError('uncertain')
        return {'status':'submitted','message':'提交完成；可见性未核验','visibility':'unverified'}


@pytest.fixture
def setup(tmp_path):
    video=tmp_path/'sample.mp4'
    video.write_bytes(b'\x00\x00\x00\x18ftypmp42-video-example')
    bridge=FakeSAU(video)
    app=create_app(tmp_path/'home',worker=False,publishing_bridge=bridge)
    publisher=app.state.publisher
    publisher.probe=lambda _: {'duration':2,'width':64,'height':64}
    clock=[1000000.0]
    publisher.clock=lambda:clock[0]
    with TestClient(app,base_url='http://127.0.0.1:8776') as client:
        token=client.get('/api/state').json()['token']
        client.headers.update({'X-JM-Token':token,'Origin':'http://127.0.0.1:8776'})
        yield client,publisher,bridge,clock


def content(**changes):
    return PublishInput(**dict({'request_id':'test-request-0001','title':'测试视频标题','material_ids':['sau:10'],
                                'account_ids':['sau:1'],'tags':['测试']},**changes))


def launch(publisher, **changes):
    ident=publisher.save(content(**changes))['id']
    return ident,publisher.launch(ident)


def test_public_catalog_never_exposes_cookie_paths(setup):
    client,p,bridge,_=setup
    response=client.get('/api/publishing/state')
    assert response.status_code==200
    assert 'private-cookie' not in response.text and '_path' not in response.text
    assert len(response.json()['accounts'])==1 and len(response.json()['platforms'])==4
    assert response.json()['worker'] is False


def test_save_draft_is_persistent_and_does_not_publish(setup):
    _,p,b,_=setup
    ident=p.save(content())['id']
    assert p.batches()[0]['state']=='draft' and p.batches()[0]['jobs']==[]
    p.tick()
    assert b.sent==[]
    reopened=Publishing(p.cfg,bridge=b)
    assert reopened.batches()[0]['id']==ident


def test_submit_records_generic_receipt_without_claiming_visibility(setup):
    _,p,b,_=setup
    ident,_=launch(p)
    assert p.tick()
    record=p.batches()[0]
    assert record['id']==ident and record['state']=='submitted'
    assert record['jobs'][0]['receipt']['visibility']=='unverified'
    assert len(b.sent)==1
    p.tick()
    assert len(b.sent)==1


def test_idempotent_save_and_launch(setup):
    _,p,b,_=setup
    first=p.save(content())
    assert p.save(content())['id']==first['id']
    p.launch(first['id'])
    p.launch(first['id'])
    assert len(p.batches()[0]['jobs'])==1
    with pytest.raises(ValueError,match='其他内容'):
        p.save(content(title='Different'))


def test_duplicate_account_video_blocked_even_changed_title(setup):
    _,p,_,_=setup
    launch(p)
    second=p.save(content(request_id='different-request',title='Different title'))['id']
    with pytest.raises(ValueError,match='重复发布'):
        p.launch(second)
    assert next(r for r in p.batches() if r['id']==second)['state']=='draft'


def test_schedule_waits_and_survives_reopen(setup):
    _,p,b,clock=setup
    launch(p,mode='scheduled',schedule_at=clock[0]+300)
    assert not p.tick() and not b.sent
    reopened=Publishing(p.cfg,bridge=b,clock=lambda:clock[0],probe=p.probe)
    clock[0]+=301
    assert reopened.tick() and len(b.sent)==1


def test_expired_schedule_rejected_on_save_and_launch(setup):
    _,p,_,clock=setup
    with pytest.raises(ValueError,match='晚于'):
        p.save(content(mode='scheduled',schedule_at=clock[0]-1))
    ident=p.save(content(mode='scheduled',schedule_at=clock[0]+3))['id']
    clock[0]+=4
    with pytest.raises(ValueError,match='已过'):
        p.launch(ident)


def test_cancel_and_pause_prevent_start_until_resume(setup):
    _,p,b,_=setup
    ident,_=launch(p)
    p.control(ident,'pause')
    assert not p.tick() and not b.sent
    p.control(ident,'resume')
    p.control(ident,'cancel')
    assert not p.tick() and p.batches()[0]['state']=='cancelled'


def test_unknown_result_blocks_retry_and_platform_clear(setup):
    client,p,b,_=setup
    ident,_=launch(p)
    b.fail=True
    assert p.tick()
    assert p.batches()[0]['state']=='unknown'
    with pytest.raises(ValueError,match='不允许'):
        p.control(ident,'resume')
    p.tick()
    assert len(b.sent)==1
    response=client.post('/api/risk/ks/clear',json={'note':'已经检查平台但还没有找到明确的作品记录'})
    assert response.status_code==400


def test_restart_marks_inflight_unknown_without_repeating(setup):
    _,p,b,_=setup
    ident,_=launch(p)
    with p.store.connect() as db:
        db.execute("UPDATE publish_jobs SET state='running' WHERE batch_id=?",(ident,))
    reopened=Publishing(p.cfg,bridge=b,clock=p.clock,probe=p.probe)
    reopened.recover()
    assert reopened.batches()[0]['state']=='unknown'
    assert p.store.rows("SELECT * FROM risk WHERE platform='ks'")
    assert not reopened.tick() and not b.sent


def test_source_account_change_stops_without_send(setup):
    _,p,b,_=setup
    launch(p)
    b.accounts[0]['_key']='changed-cookie-file'
    assert not p.tick() and not b.sent
    assert p.batches()[0]['state']=='paused'


def test_modified_media_stops_without_send(setup):
    _,p,b,_=setup
    launch(p)
    b.path.write_bytes(b'changed')
    assert not p.tick() and not b.sent
    assert p.batches()[0]['state']=='failed'


def test_service_outage_waits_before_send(setup):
    _,p,b,clock=setup
    launch(p)
    b.offline=True
    assert not p.tick() and not b.sent
    record=p.batches()[0]
    assert record['state']=='queued' and record['jobs'][0]['due']>clock[0]
    b.offline=False
    clock[0]+=31
    assert p.tick() and len(b.sent)==1


@pytest.mark.parametrize('field,value,message',[
    ('platform_draft',True,'仅支持视频号'),('product_link','https://example.com/item','仅支持抖音')])
def test_platform_specific_features_fail_closed(setup,field,value,message):
    _,p,b,_=setup
    ident=p.save(content(**{field:value}))['id']
    with pytest.raises(ValueError,match=message):p.launch(ident)
    assert not b.sent


def test_tencent_platform_draft_maps_to_content(setup):
    _,p,b,_=setup
    b.accounts[0]['platform']='tencent'
    launch(p,platform_draft=True)
    p.tick()
    assert b.sent[0][2]['platform_draft'] is True


def test_shared_platform_interval_persists(setup):
    _,p,b,clock=setup
    b.accounts.append(dict(b.accounts[0],id='sau:2',_key='identity-two',_file='second.json'))
    launch(p,account_ids=['sau:1','sau:2'])
    p.tick()
    assert len(b.sent)==1
    p.tick()
    assert len(b.sent)==1
    record=p.batches()[0]
    waiting=next(j for j in record['jobs'] if j['state']=='queued')
    assert waiting['due']>=clock[0]+1800
    clock[0]+=1801
    p.tick()
    assert len(b.sent)==2


def test_concurrent_tick_sends_only_once(setup):
    _,p,b,_=setup
    launch(p)
    b.entered,b.release=threading.Event(),threading.Event()
    with ThreadPoolExecutor(2) as pool:
        future=pool.submit(p.tick)
        assert b.entered.wait(3)
        assert not p.tick()
        b.release.set()
        assert future.result()
    assert len(b.sent)==1


def test_stop_all_includes_content_queue(setup):
    client,p,b,_=setup
    launch(p)
    assert client.post('/api/stop',json={}).status_code==200
    assert not p.tick() and not b.sent
    assert p.batches()[0]['state']=='paused'


def test_draft_edit_only_before_execution(setup):
    _,p,_,_=setup
    ident=p.save(content())['id']
    p.save(content(title='Updated'),ident)
    assert p.batches()[0]['payload']['title']=='Updated'
    p.launch(ident)
    with pytest.raises(ValueError,match='只有'):
        p.save(content(title='Third'),ident)


def test_upload_local_validation_dedupe_and_download(setup):
    client,p,b,_=setup
    first=client.post('/api/publishing/materials/upload?name=测试.mp4',content=b'video-data')
    assert first.status_code==200
    ident=first.json()['id']
    assert client.get('/api/publishing/materials/'+ident+'/file').content==b'video-data'
    assert client.post('/api/publishing/materials/upload?name=other.mp4',content=b'video-data').json()['id']==ident
    assert len(p.local_materials())==1 and not b.uploads
    assert client.delete('/api/publishing/materials/'+ident).status_code==200
    assert not p.local_materials()


@pytest.mark.parametrize('name,body', [('empty.mp4',b''),('../bad.mp4',b'a'),('file.exe',b'a'),('bad\\file.mp4',b'a')])
def test_invalid_upload_leaves_no_partial_file(setup,name,body):
    from urllib.parse import quote
    client,p,_,_=setup
    assert client.post('/api/publishing/materials/upload?name='+quote(name,safe=''),content=body).status_code==400
    assert list(p.media.iterdir())==[]


def test_upload_limits_and_origin_are_checked_before_streaming(setup):
    client,p,_,_=setup
    assert client.post('/api/publishing/materials/upload?name=x.mp4',content=b'x',headers={'Content-Length':str(MAX_UPLOAD+1)}).status_code==413
    assert client.post('/api/publishing/materials/upload?name=x.mp4',content=b'x',headers={'Origin':'https://example.com'}).status_code==403
    assert client.post('/api/publishing/materials/upload?name=x.mp4',content=b'x',headers={'X-JM-Token':''}).status_code==403
    assert list(p.media.iterdir())==[]


def test_invalid_video_probe_has_friendly_error(tmp_path):
    p=tmp_path/'invalid.mp4'
    p.write_bytes(b'not a video')
    with pytest.raises(ValueError):probe_video(p)


@pytest.mark.parametrize('url',['https://127.0.0.1:5409','http://example.com:5409','http://127.0.0.1:5409/path','http://user:secret@127.0.0.1:5409','http://127.0.0.1:5409?q=x','http://localhost:80'])
def test_bridge_settings_reject_non_loopback_or_extra_components(url):
    with pytest.raises(ValueError):PublishingSettings(sau_url=url)


def test_active_queue_blocks_connection_setting_changes(setup):
    client,p,_,_=setup
    launch(p)
    response=client.put('/api/publishing/settings',json=PublishingSettings().model_dump())
    assert response.status_code==400


def test_local_media_cannot_delete_while_used_by_draft(setup):
    client,p,_,_=setup
    ident=client.post('/api/publishing/materials/upload?name=x.mp4',content=b'video').json()['id']
    p.save(content(material_ids=[ident]))
    assert client.delete('/api/publishing/materials/'+ident).status_code==400


def test_local_media_uploads_only_at_execution(setup):
    client,p,b,_=setup
    ident=client.post('/api/publishing/materials/upload?name=x.mp4',content=b'video').json()['id']
    launch(p,material_ids=[ident])
    assert not b.uploads
    p.tick()
    assert len(b.uploads)==1 and len(b.sent)==1


@pytest.mark.parametrize('value',['../x','a/b','a\\b','C:private','a\n.json','..'])
def test_unsafe_sau_references_rejected(value):
    with pytest.raises(ValueError):filename(value)


@pytest.mark.parametrize('outcome,expected',[('submitted','submitted'),('not_sent','failed')])
def test_resolve_unknown_records_evidence_without_retry_or_unlock(setup,outcome,expected):
    client,p,b,_=setup
    launch(p)
    b.fail=True
    p.tick()
    job=p.batches()[0]['jobs'][0]['id']
    response=client.post(f'/api/publishing/jobs/{job}/resolve',json={'outcome':outcome,'note':'已经到平台作品管理核对并记录本次提交结果'})
    assert response.status_code==200
    assert p.batches()[0]['jobs'][0]['state']==expected
    assert p.store.rows("SELECT 1 FROM risk WHERE platform='ks'")
    p.tick()
    assert len(b.sent)==1
    assert client.post(f'/api/publishing/jobs/{job}/resolve',json={'outcome':outcome,'note':'已经到平台作品管理核对并记录本次提交结果'}).status_code==400


def test_duplicate_account_alias_rejected_before_queue(setup):
    _,p,b,_=setup
    b.accounts.append(dict(b.accounts[0],id='sau:2'))
    ident=p.save(content(account_ids=['sau:1','sau:2']))['id']
    with pytest.raises(ValueError,match='重复记录'):p.launch(ident)
    assert not p.batches()[0]['jobs']


def test_duplicate_material_copy_rejected_before_queue(setup):
    _,p,b,_=setup
    b.materials.append(dict(b.materials[0],id='sau:11'))
    ident=p.save(content(material_ids=['sau:10','sau:11']))['id']
    with pytest.raises(ValueError,match='重复副本'):p.launch(ident)
    assert not p.batches()[0]['jobs']


def test_same_local_media_uploaded_once_for_multiple_accounts(setup):
    client,p,b,clock=setup
    b.accounts.append(dict(b.accounts[0],id='sau:2',_key='identity-two',_file='second.json'))
    media=client.post('/api/publishing/materials/upload?name=x.mp4',content=b'video').json()['id']
    launch(p,material_ids=[media],account_ids=['sau:1','sau:2'])
    p.tick()
    clock[0]+=1801
    p.tick()
    assert len(b.uploads)==1 and len(b.sent)==2


def test_daily_limit_is_shared_across_accounts(setup):
    _,p,b,clock=setup
    p.cfg.config.save({'publish_daily_limit':1})
    b.accounts.append(dict(b.accounts[0],id='sau:2',_key='identity-two',_file='second.json'))
    launch(p,account_ids=['sau:1','sau:2'])
    p.tick()
    clock[0]+=1801
    p.tick()
    assert len(b.sent)==1
    clock[0]+=86400
    p.tick()
    assert len(b.sent)==2


def test_failed_upload_never_calls_publish(setup,monkeypatch):
    client,p,b,_=setup
    def fail(_):raise SAUUnavailable('upload down')
    monkeypatch.setattr(b,'upload',fail)
    media=client.post('/api/publishing/materials/upload?name=x.mp4',content=b'video').json()['id']
    launch(p,material_ids=[media])
    p.tick()
    assert p.batches()[0]['state']=='failed' and not b.sent
    assert not p.store.rows('SELECT * FROM risk')


def test_changed_service_configuration_cannot_redirect_old_queue(setup):
    client,p,b,_=setup
    ident,_=launch(p)
    p.control(ident,'pause')
    config=PublishingSettings(sau_url='http://127.0.0.1:5410').model_dump()
    assert client.put('/api/publishing/settings',json=config).status_code==200
    p.control(ident,'resume')
    p.tick()
    assert not b.sent and p.batches()[0]['state']=='paused'


def test_changing_service_does_not_reuse_another_servers_media_reference(setup):
    client,p,b,clock=setup
    media=client.post('/api/publishing/materials/upload?name=x.mp4',content=b'video').json()['id']
    launch(p,material_ids=[media]);p.tick()
    assert len(b.uploads)==1 and p.local_materials()[0]['_file']
    assert client.put('/api/publishing/settings',json=PublishingSettings(sau_url='http://127.0.0.1:5410').model_dump()).status_code==200
    assert not p.local_materials()[0]['_file']
    b.accounts.append(dict(b.accounts[0],id='sau:2',_key='other-account',_file='other.json'))
    launch(p,request_id='second-service-job',material_ids=[media],account_ids=['sau:2'])
    clock[0]+=1801;p.tick()
    assert len(b.uploads)==2 and len(b.sent)==2
