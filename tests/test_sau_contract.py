import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest
from jm_workbench.core.config import Config
from jm_workbench.publishing.sau import SAUBridge, SAUUnavailable
from jm_workbench.publishing.models import PublishInput


@pytest.fixture
def bridge_server(tmp_path):
    calls=[]
    root=tmp_path/'sau'
    (root/'videoFile').mkdir(parents=True)
    (root/'videoFile'/'video.mp4').write_bytes(b'video-bytes')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if self.path=='/jmGuard':data={'version':1,'single_submit':True,'timeout_seconds':600}
            elif self.path=='/getAccounts':data=[[1,4,'cookie.json','Test',1],[2,99,'ignored.json','Unknown platform',1]]
            elif self.path=='/getFiles':data=[{'id':1,'filename':'视频.mp4','file_path':'video.mp4'},{'id':2,'filename':'Unsafe','file_path':'../outside.mp4'}]
            elif self.path=='/redirect':
                self.send_response(302);self.send_header('Location','https://example.com');self.end_headers();return
            else:data=None
            raw=json.dumps({'code':200,'data':data}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_POST(self):
            raw=self.rfile.read(int(self.headers['Content-Length']))
            calls.append((self.path,raw,dict(self.headers)))
            data={'filepath':'upload.mp4'} if self.path=='/uploadSave' else None
            body=json.dumps({'code':200,'data':data}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    cfg=Config(tmp_path/'home');cfg.save({'sau_root':str(root),'sau_url':f'http://127.0.0.1:{server.server_port}'})
    yield SAUBridge(cfg),calls,root
    server.shutdown();server.server_close();thread.join()


def test_catalog_filters_unsupported_platform_and_unsafe_material(bridge_server):
    bridge,_,_=bridge_server
    catalog=bridge.catalog()
    assert len(catalog['accounts'])==1 and catalog['accounts'][0]['platform']=='ks'
    assert catalog['accounts'][0]['status']=='recorded'
    assert len(catalog['materials'])==1 and catalog['materials'][0]['available']


@pytest.mark.parametrize('platform,type_id',[('xhs',1),('tencent',2),('dy',3),('ks',4)])
def test_actual_http_payload_uses_single_account_video_and_jm_scheduling(bridge_server,platform,type_id):
    bridge,calls,_=bridge_server
    payload=PublishInput(request_id='contract-1234',title='标题',tags=['话题'],material_ids=['sau:1'],account_ids=['sau:1'],mode='scheduled',schedule_at=2000000000).model_dump()
    result=bridge.publish({'platform':platform,'_file':'cookie.json'},'video.mp4',payload)
    path,body,_=calls[0];data=json.loads(body)
    assert path=='/postVideo' and data['type']==type_id
    assert data['fileList']==['video.mp4'] and data['accountList']==['cookie.json']
    assert data['title']=='标题' and data['tags']==['话题']
    assert data['enableTimer'] is False and data['dailyTimes']==[]
    assert data['jmGuarded'] is True
    assert result['status']=='submitted' and result['visibility']=='unverified'


def test_upload_uses_sau_multipart_contract(bridge_server):
    bridge,calls,root=bridge_server
    assert bridge.upload(root/'videoFile/video.mp4')=='upload.mp4'
    path,body,headers=calls[0]
    assert path=='/uploadSave' and b'name="file"' in body and b'video-bytes' in body
    assert headers['Content-Type'].startswith('multipart/form-data; boundary=')
    assert int(headers['Content-Length'])==len(body)


def test_service_redirect_is_not_followed(bridge_server):
    bridge,calls,_=bridge_server
    with pytest.raises(SAUUnavailable):bridge.request('/redirect')
    assert not calls
