import io
import json
from types import SimpleNamespace
import pytest
from jm_workbench.community.browser_connection import relay_connection,uses_relay,connect_relay
from jm_workbench.adapters.errors import LocalBrowserError


@pytest.fixture
def relay(tmp_path):
    secret=tmp_path/'secret';secret.write_text('a'*64)
    cfg=SimpleNamespace(values={'browser_open_mode':'daily','community_relay_accounts':['a'],
        'community_relay_port':18799,'community_relay_secret_file':str(secret)})
    account={'id':'a','platform':'juejin'}
    return cfg,account


class Opener:
    def __init__(self,ws='ws://127.0.0.1:18799/cdp',tabs=None):
        self.ws=ws;self.tabs=tabs if tabs is not None else [{'url':'https://juejin.cn/user/123'}];self.requests=[]
    def open(self,req,timeout):
        self.requests.append(req)
        return io.BytesIO(json.dumps({'webSocketDebuggerUrl':self.ws} if req.full_url.endswith('/version') else self.tabs).encode())


def test_verified_loopback_connection_keeps_secret_out_of_url(relay):
    cfg,a=relay;o=Opener();ws,headers=relay_connection(cfg,a,o)
    assert ws=='ws://127.0.0.1:18799/cdp' and headers['Authorization']=='Bearer '+'a'*64
    assert len(o.requests)==2 and all('a'*64 not in r.full_url for r in o.requests)


@pytest.mark.parametrize('url',['ws://evil.example/cdp','ws://127.0.0.1:19999/cdp',
    'ws://u:p@127.0.0.1:18799/cdp','ws://127.0.0.1:18799/cdp?token=secret',
    'ws://127.0.0.1:18799/other','wss://127.0.0.1:18799/cdp'])
def test_untrusted_relay_cannot_redirect_browser_credentials(relay,url):
    cfg,a=relay;o=Opener(ws=url)
    with pytest.raises(LocalBrowserError):relay_connection(cfg,a,o)
    assert len(o.requests)==1


@pytest.mark.parametrize('tabs',[[{'url':'https://evil.example/'}],[{'url':'https://juejin.cn.evil.example/'}],
    [{'url':'https://u:p@juejin.cn/'}],[{'url':'http://juejin.cn/'}],[]])
def test_platform_requires_deliberately_shared_https_tab(relay,tabs):
    cfg,a=relay
    with pytest.raises(LocalBrowserError,match='共享组'):relay_connection(cfg,a,Opener(tabs=tabs))


def test_connection_is_account_scoped_and_never_falls_back(relay):
    cfg,a=relay
    assert uses_relay(cfg,a)
    assert not uses_relay(cfg,{'id':'other'})
    cfg.values['browser_open_mode']='account'
    assert not uses_relay(cfg,a)


def test_error_does_not_expose_token(relay):
    cfg,a=relay
    class Bad:
        def open(self,*args,**kwargs):raise RuntimeError('a'*64)
    with pytest.raises(LocalBrowserError) as error:relay_connection(cfg,a,Bad())
    assert 'a'*64 not in str(error.value)


def test_failed_cdp_connection_is_sanitized(monkeypatch,relay):
    cfg,a=relay
    monkeypatch.setattr('jm_workbench.community.browser_connection.relay_connection',lambda *x:('ws://127.0.0.1:18799/cdp',{'Authorization':'secret'}))
    def fail(*args,**kwargs):raise RuntimeError('secret')
    with pytest.raises(LocalBrowserError) as error:connect_relay(SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=fail)),cfg,a)
    assert 'secret' not in str(error.value)


def test_malformed_shared_urls_cannot_enable_transport(relay):
    cfg,a=relay
    with pytest.raises(LocalBrowserError,match='共享组'):
        relay_connection(cfg,a,Opener(tabs=[{'url':'https://[bad'},None,{'url':[]}]))


def test_bound_account_never_launches_or_uses_legacy_browser(monkeypatch,relay):
    from jm_workbench.community.adapters import CommunityAdapter,PreflightStopped
    cfg,a=relay;adapter=CommunityAdapter(cfg)
    def forbidden(*args,**kwargs):pytest.fail('legacy browser accessed')
    monkeypatch.setattr('jm_workbench.community.adapters.endpoint',forbidden)
    monkeypatch.setattr(adapter,'open',forbidden)
    def disconnected(*args):raise LocalBrowserError('连接失效')
    monkeypatch.setattr('jm_workbench.community.adapters.relay_connection',disconnected)
    monkeypatch.setattr('jm_workbench.community.adapters.connect_relay',disconnected)
    with pytest.raises(PreflightStopped,match='连接失效'):adapter.ensure_connection(a)
    with pytest.raises(PreflightStopped,match='连接失效'):adapter.connect_browser(None,a)


def test_juejin_uses_same_injected_connection_for_read_and_write(monkeypatch):
    from jm_workbench.community.adapters import CommunityAdapter
    adapter=CommunityAdapter(SimpleNamespace(values={}))
    marker=object();calls=[]
    def connect(pw,a):calls.append(a);return marker
    monkeypatch.setattr(adapter,'connect_browser',connect)
    assert adapter.juejin_browser().connect(None,{'id':'expected'}) is marker
    assert calls==[{'id':'expected'}]
