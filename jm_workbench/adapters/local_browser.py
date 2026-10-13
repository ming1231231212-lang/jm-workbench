"""User-triggered navigation in the user's normal Chrome, without profile flags."""
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
from .errors import LocalBrowserError


def validate_url(url):
    if not isinstance(url, str) or not url or len(url) > 8192:
        raise ValueError('网页地址无效')
    if any(ord(c) < 33 or ord(c) == 127 for c in url) or '\\' in url:
        raise ValueError('网页地址不能包含空白、控制字符或反斜线')
    try:
        parsed = urlsplit(url)
        port = parsed.port
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError()
    except ValueError:
        raise ValueError('只支持不含登录凭据的 HTTP / HTTPS 网页地址') from None
    return url


def chrome_executable(config):
    path = Path(config.values['chrome_path'])
    if not path.is_file() or path.name.lower() not in ('chrome.exe', 'google-chrome', 'chrome', 'chromium'):
        raise LocalBrowserError('未找到本地 Google Chrome，请在工作台设置中检查程序路径')
    return str(path)


def open_local_url(config, url):
    url = validate_url(url)
    try:
        # Chrome forwards to its existing default-profile window. Do not set a
        # user-data-dir, incognito, remote-debugging, or new-window argument.
        subprocess.Popen([chrome_executable(config), url], shell=False,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as ex:
        raise LocalBrowserError('本地 Chrome 未能打开，请检查程序路径后重试') from ex
    return {'message': ('已交给日常 Chrome 打开；网页登录和提交在网站完成' if config.values.get('community_browser_execution')=='web' else '已交给日常 Chrome 打开；自动任务连接需单独核验'),
            'browser_mode': 'daily', 'account_verified': False}


if __name__ == '__main__':
    import argparse
    from ..core.config import Config
    parser = argparse.ArgumentParser()
    parser.add_argument('url')
    args = parser.parse_args()
    open_local_url(Config(), args.url)
