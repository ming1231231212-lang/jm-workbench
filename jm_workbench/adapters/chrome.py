import json
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse
from .errors import LocalBrowserError
from ..core.platforms import PLATFORMS


def endpoint(profile):
    """Resolve the websocket from the selected profile, never a global cached port."""
    try:
        lines = (Path(profile) / 'DevToolsActivePort').read_text().splitlines()
        port = int(lines[0])
        if not 1024 <= port <= 65535 or not lines[1].startswith('/devtools/browser/'):
            raise ValueError()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/json/version', timeout=3) as response:
            version = json.load(response)
        ws = urlparse(version['webSocketDebuggerUrl'])
        if (ws.scheme, ws.hostname, ws.port, ws.path) != ('ws', '127.0.0.1', port, lines[1]) or ws.username or ws.password or ws.query or ws.fragment:
            raise ValueError()
        return version['webSocketDebuggerUrl']
    except Exception as ex:
        raise LocalBrowserError('账号浏览器未连接，请先打开该账号浏览器并登录') from ex


def open_browser(config, account):
    profile = Path(account['profile_dir']).resolve()
    profile.mkdir(parents=True, exist_ok=True)
    chrome = Path(config.values['chrome_path'])
    if not chrome.is_file() or chrome.name.lower() not in ('chrome.exe', 'google-chrome', 'chrome', 'chromium'):
        raise LocalBrowserError('请在设置中配置有效的Google Chrome程序路径')
    try:
        endpoint(profile)
    except LocalBrowserError:
        subprocess.Popen([str(chrome), f'--user-data-dir={profile}', '--remote-debugging-port=0',
                          '--no-first-run', '--no-default-browser-check', PLATFORMS[account['platform']]['home']],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(20):
            time.sleep(.5)
            try:
                endpoint(profile)
                break
            except LocalBrowserError:
                continue
        else:
            raise LocalBrowserError('Chrome未开启调试连接；请关闭此资料目录的旧窗口，再打开账号浏览器')
    else:
        # Opening the homepage does not mutate the profile's platform account.
        subprocess.Popen([str(chrome), f'--user-data-dir={profile}', PLATFORMS[account['platform']]['home']],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {'message': '账号浏览器已打开，请完成平台登录后检查连接'}
