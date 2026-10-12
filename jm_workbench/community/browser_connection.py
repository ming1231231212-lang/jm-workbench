"""Opt-in local extension transport; identity checks remain in platform adapters."""
import json
import re
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from ..adapters.errors import LocalBrowserError


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def uses_relay(config, account):
    values = config.values if config else {}
    return (values.get('browser_open_mode', 'daily') == 'daily' and
            account.get('id') in values.get('community_relay_accounts', []))


def relay_connection(config, account, opener=None):
    """Check authenticated loopback relay and a deliberately shared platform tab."""
    if not uses_relay(config, account):
        raise LocalBrowserError('此账号尚未绑定日常 Chrome 扩展连接')
    host = {'tieba': 'tieba.baidu.com', 'juejin': 'juejin.cn'}.get(account['platform'])
    if not host:
        raise LocalBrowserError('此平台尚未验证日常 Chrome 扩展连接')
    values = config.values
    port = values.get('community_relay_port')
    if type(port) is not int or not 1024 <= port <= 65535:
        raise LocalBrowserError('本地扩展连接端口无效')
    try:
        token = Path(values['community_relay_secret_file']).read_text(encoding='utf-8').strip()
        if not re.fullmatch(r'[0-9a-f]{64}', token):
            raise ValueError()
    except (OSError, KeyError, ValueError):
        raise LocalBrowserError('本地扩展配对凭据不可用，请重新配对') from None
    headers = {'Authorization': 'Bearer '+token}
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    def get(path):
        req = urllib.request.Request(f'http://127.0.0.1:{port}'+path, headers=headers)
        with opener.open(req, timeout=4) as response:
            return json.loads(response.read(1_000_000))
    try:
        info = get('/json/version')
        ws = info['webSocketDebuggerUrl']
        url = urlsplit(ws)
        if (url.scheme, url.hostname, url.port, url.path) != ('ws', '127.0.0.1', port, '/cdp') or url.username or url.password or url.query or url.fragment:
            raise ValueError()
        tabs = get('/json/list')
        if not isinstance(tabs, list):
            raise ValueError()
    except Exception:
        # Never propagate headers, tokens or remote error bodies into the UI/log.
        raise LocalBrowserError('日常 Chrome 扩展未连接或配对已失效，请打开 OpenClaw 扩展检查连接') from None
    def matches(tab):
        try:
            url = urlsplit(tab.get('url', ''))
            return url.scheme == 'https' and url.netloc == host
        except (ValueError, TypeError, AttributeError):
            return False
    if not any(matches(t) for t in tabs):
        raise LocalBrowserError('请在日常 Chrome 的对应平台页面点击 OpenClaw 扩展，将该标签页加入共享组')
    return ws, headers


def connect_relay(pw, config, account):
    ws, headers = relay_connection(config, account)
    try:
        browser = pw.chromium.connect_over_cdp(ws, headers=headers, timeout=10000)
        if len(browser.contexts) != 1:
            raise ValueError()
        return browser
    except Exception:
        raise LocalBrowserError('日常 Chrome 扩展连接未完成；没有切换浏览器或账号') from None
