from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from jm_workbench.adapters import local_browser, chrome
from jm_workbench.adapters.errors import LocalBrowserError
from jm_workbench.community.adapters import CommunityAdapter, PreflightStopped
from jm_workbench.web.app import create_app


@pytest.fixture
def setup(tmp_path, monkeypatch):
    executable = tmp_path/'chrome.exe'
    executable.touch()
    config = SimpleNamespace(values={'chrome_path':str(executable)})
    calls = []
    monkeypatch.setattr(local_browser.subprocess, 'Popen', lambda argv, **kw: calls.append((argv, kw)))
    return config, calls


@pytest.mark.parametrize('url', ['https://tieba.baidu.com/', 'https://juejin.cn/post/123#comment', 'http://127.0.0.1:5409/#/account-management'])
def test_daily_browser_only_passes_url_and_executable(setup, url):
    config, calls = setup
    result = local_browser.open_local_url(config, url)
    assert calls[0][0] == [config.values['chrome_path'], url]
    assert calls[0][1]['shell'] is False
    assert result['browser_mode'] == 'daily' and not result['account_verified']


@pytest.mark.parametrize('url', ['file:///C:/secret', 'javascript:alert(1)', '--user-data-dir=bad', 'https://a:password@example.com/', 'https://example.com\n--incognito', 'https://example.com\\x', 'https://', 'http://a:bad', 'https://a/ x'])
def test_invalid_urls_do_not_launch(setup, url):
    config,calls=setup
    with pytest.raises(ValueError):local_browser.open_local_url(config,url)
    assert not calls


def test_missing_or_failing_chrome_has_no_fallback(setup, monkeypatch):
    config,calls=setup
    config.values['chrome_path'] = 'missing/chrome.exe'
    with pytest.raises(LocalBrowserError):local_browser.open_local_url(config,'https://tieba.baidu.com/')
    assert not calls
    monkeypatch.setattr(local_browser,'chrome_executable',lambda c:'chrome.exe')
    def fail(*a,**kw):raise OSError('unavailable')
    monkeypatch.setattr(local_browser.subprocess,'Popen',fail)
    with pytest.raises(LocalBrowserError):local_browser.open_local_url(config,'https://tieba.baidu.com/')


def test_account_entrypoints_use_daily_and_do_not_create_profile(setup, tmp_path):
    config,calls=setup
    profile=tmp_path/'must-not-be-created'
    chrome.open_browser(config, {'platform':'ks','profile_dir':str(profile)})
    CommunityAdapter(config).open({'platform':'tieba','profile_dir':str(profile)},'https://tieba.baidu.com/')
    assert len(calls)==2 and all(len(argv)==2 for argv,kw in calls)
    assert not profile.exists()
    with pytest.raises(ValueError):CommunityAdapter(config).open({'platform':'tieba'},'https://evil.example/')
    assert len(calls)==2


def test_daily_mode_never_spawns_profile_or_navigation_on_background_restore(setup, monkeypatch):
    from jm_workbench.community import adapters
    config,calls=setup
    def offline(profile):raise LocalBrowserError('offline')
    monkeypatch.setattr(adapters,'endpoint',offline)
    with pytest.raises(PreflightStopped,match='日常 Chrome'):
        CommunityAdapter(config).ensure_connection({'platform':'tieba','profile_dir':'missing'})
    assert not calls


def test_browser_api_requires_token_validates_and_preserves_accounts(setup,tmp_path):
    config,calls=setup
    app=create_app(tmp_path/'state',worker=False)
    app.state.cfg.config.values.update(config.values)
    with TestClient(app,base_url='http://127.0.0.1') as client:
        before=client.get('/api/state').json()
        assert before['settings']['browser_open_mode']=='daily'
        assert client.post('/api/browser/open',json={'url':'https://tieba.baidu.com/'}).status_code==403
        headers={'X-JM-Token':before['token']}
        assert client.post('/api/browser/open',json={'url':'file:///C:/secret'},headers=headers).status_code==400
        assert client.post('/api/browser/open',json={'url':'https://tieba.baidu.com/'},headers=headers).status_code==200
        after=client.get('/api/state').json()
        assert after['accounts']==before['accounts'] and after['runs']==before['runs']
        assert len(calls)==1
