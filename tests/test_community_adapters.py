import pytest
from jm_workbench.core.config import Config
from jm_workbench.community.adapters import CommunityAdapter,NotSubmitted,tieba_receipt,tieba_identity
from jm_workbench.community.registry import destination,safe_post_url


@pytest.mark.parametrize('p,response,expected_url',[('dev',{'id':7,'url':'https://dev.to/test/article'},'https://dev.to/api/articles'),('x',{'data':{'id':'8'}},'https://api.x.com/2/tweets'),('reddit',{'json':{'data':{'id':'abc','url':'https://www.reddit.com/r/test/comments/abc'}}},'https://oauth.reddit.com/api/submit'),('huggingface',{'num':3},'https://huggingface.co/api/models/test/repo/discussions')])
def test_api_contract_single_write(tmp_path,p,response,expected_url):
    calls=[]
    def transport(*args,**kwargs):calls.append((args,kwargs));return response
    a=CommunityAdapter(Config(tmp_path),transport)
    r=a.publish({'platform':p},'local-secret',{'title':'Testing title','body':'Testing body','tags':['ai']},'test/repo' if p=='huggingface' else 'test' if p=='reddit' else '')
    assert len(calls)==1 and calls[0][0][0]=='POST' and calls[0][0][1]==expected_url
    assert r['post_id'] and r['visibility']=='unverified'
    if p=='reddit':assert calls[0][1]['form'] and calls[0][0][3]['kind']=='self'
    if p=='dev':assert calls[0][0][3]['article']['published'] is True


@pytest.mark.parametrize('p,response,identity',[('dev',{'id':123},'123'),('x',{'data':{'id':'abc'}},'abc'),('reddit',{'id':'abc','name':'sample'},'abc'),('huggingface',{'id':'id','name':'sample'},'id')])
def test_read_identity(tmp_path,p,response,identity):
    calls=[]
    def request(*args,**kwargs):calls.append(args);return response
    a=CommunityAdapter(Config(tmp_path),request)
    assert a.check({'platform':p},'secret')==identity
    assert calls[0][0]=='GET'


def test_unsupported_platform_never_calls_transport(tmp_path):
    calls=[]
    a=CommunityAdapter(Config(tmp_path),lambda *args: calls.append(args))
    with pytest.raises(NotSubmitted):a.publish({'platform':'hackernews'},'',{'title':'x','body':'y'},'')
    assert not calls


@pytest.mark.parametrize('data',[{'error_code':'220901','data':{'info':{'need_vcode':1}}},{'errno':403},{'data':{'error_code':1}}])
def test_tieba_captcha_and_rejection_stop(data):
    with pytest.raises(NotSubmitted):tieba_receipt(data)


def test_tieba_receipt_requires_id_not_success_message():
    assert tieba_receipt({'error_code':0,'data':{'tid':'123456'}})['url']=='https://tieba.baidu.com/p/123456'
    with pytest.raises(RuntimeError):tieba_receipt({'error_code':0,'message':'ok'})


@pytest.mark.parametrize('url',['javascript:alert(1)','https://tieba.baidu.com.evil.test/p/1','https://user:pass@tieba.baidu.com/p/1','http://127.0.0.1/','https://tieba.baidu.com:8443/p/1'])
def test_post_url_rejects_other_hosts_and_unsafe_urls(url):
    with pytest.raises(ValueError):safe_post_url('tieba',url)


def test_destination_rejects_path_injection():
    for p,value in [('reddit','a/../admin'),('huggingface','../repo?x=1'),('v2ex','//evil.test'),('tieba','')]:
        with pytest.raises(ValueError):destination(p,value)


def test_dev_frontmatter_preflight_and_x_limit(tmp_path):
    calls=[];a=CommunityAdapter(Config(tmp_path),lambda *args: calls.append(args))
    with pytest.raises(NotSubmitted):a.publish({'platform':'dev'},'secret',{'title':'test','body':'---\npublished: false\n---'},'')
    with pytest.raises(NotSubmitted):a.publish({'platform':'x'},'secret',{'title':'test','body':'x'*300},'')
    assert not calls


@pytest.mark.parametrize('name',['', 'original', 'renamed'])
def test_tieba_identity_does_not_depend_on_nickname(name):
    from types import SimpleNamespace
    page=SimpleNamespace(url='https://tieba.baidu.com/',evaluate=lambda _:dict(authenticated=True,id='123',name=name))
    assert tieba_identity(page)=='123'


@pytest.mark.parametrize('data',[
    dict(authenticated=False,id='123',name='stale'),
    dict(authenticated=True,id='0',name='name'),
    dict(authenticated=True,id='',name='name'),
])
def test_tieba_identity_requires_authenticated_id(data):
    from types import SimpleNamespace
    with pytest.raises(NotSubmitted):
        tieba_identity(SimpleNamespace(url='https://tieba.baidu.com/',evaluate=lambda _:data))


def test_tieba_browser_disconnect_is_actionable(tmp_path):
    a=CommunityAdapter(Config(tmp_path))
    with pytest.raises(NotSubmitted,match='浏览器未连接'):
        a.check({'platform':'tieba','profile_dir':str(tmp_path/'missing-profile')},'')


def test_existing_tab_sync_never_opens_page_and_rejects_conflicting_accounts():
    from types import SimpleNamespace
    from jm_workbench.community.adapters import tieba_existing_identity
    def page(identity):return SimpleNamespace(url='https://tieba.baidu.com/',evaluate=lambda _:dict(authenticated=True,id=identity))
    with pytest.raises(NotSubmitted,match='打开百度贴吧'):
        tieba_existing_identity(SimpleNamespace(pages=[]))
    with pytest.raises(NotSubmitted,match='身份不一致'):
        tieba_existing_identity(SimpleNamespace(pages=[page('123'),page('456')]))
    assert tieba_existing_identity(SimpleNamespace(pages=[page('123'),page('123')]))=='123'
