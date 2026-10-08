"""Application-local Windows runtime. Never touches an existing development service."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request

BUNDLE = Path(__file__).resolve().parents[2]


def instance_id(home):
    return hashlib.sha256(str(Path(home).resolve()).casefold().encode()).hexdigest()[:24]


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def default_home():
    return Path(os.environ.get('JM_HOME') or Path(os.environ['LOCALAPPDATA']) / 'JMWorkbench').resolve()


def free_port(preferred, excluded=()):
    for port in range(preferred, preferred + 100):
        if port in excluded:
            continue
        with socket.socket() as sock:
            try:
                # A failed bind never leads to terminating the current port owner.
                if os.name == 'nt':
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                sock.bind(('127.0.0.1', port))
                return port
            except OSError:
                pass
    raise RuntimeError('没有空闲的本机端口，请退出多余的工作台实例后重试')


def health(url, home):
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url + '/api/health', timeout=1) as response:
            value = json.load(response)
        return value.get('app_id') == 'jm-workbench' and value.get('instance_id') == instance_id(home)
    except (OSError, ValueError):
        return False


def browser_path(bundle=BUNDLE):
    installed = () if os.environ.get('JM_BUNDLED_BROWSER') == '1' else (os.environ.get('PROGRAMFILES'), os.environ.get('PROGRAMFILES(X86)'), os.environ.get('LOCALAPPDATA'))
    for base in installed:
        if base:
            path = Path(base) / 'Google/Chrome/Application/chrome.exe'
            if path.is_file():
                return path
    paths = sorted((bundle / 'browser').glob('**/chrome.exe'))
    if not paths:
        raise RuntimeError('浏览器文件缺失，请完整解压发行包，或安装 Google Chrome')
    return paths[0]


def configure(home, bundle=BUNDLE):
    home.mkdir(parents=True, exist_ok=True)
    path = home / 'config.local.json'
    values = read_json(path)
    old = read_json(home / 'portable-defaults.json')
    defaults = {'chrome_path': str(browser_path(bundle)), 'crawler_root': '', 'crawler_python': '',
                'sau_root': str(home / 'video-publisher')}
    for key, value in defaults.items():
        if key not in values or (key in old and values[key] == old[key]):
            values[key] = value
    # Preserve the connector port across launches and upgrades: job snapshots include it.
    port = read_json(home / 'portable-ports.json').get('sau', 5419)
    defaults.update(sau_url=f'http://127.0.0.1:{port}', sau_web_url=f'http://127.0.0.1:{port}')
    for key in ('sau_url', 'sau_web_url'):
        if key not in values or (key in old and values[key] == old[key]):
            values[key] = defaults[key]
    if not path.exists() or values != read_json(path):
        atomic_json(path, values)
    atomic_json(home / 'portable-defaults.json', defaults)
    return values


class InstanceLock:
    def __init__(self, home):
        self.stream = (home / 'portable.lock').open('a+b')
        if self.stream.seek(0, 2) == 0:
            self.stream.write(b'0')
            self.stream.flush()

    def acquire(self):
        self.stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def close(self):
        self.stream.close()


def open_ui(url, home):
    chrome = browser_path()
    # Workbench UI has its own profile; platform accounts have separate profiles inside JM_HOME.
    subprocess.Popen([str(chrome), '--user-data-dir=' + str(home / 'workbench-browser'),
                      '--no-first-run', '--no-default-browser-check', url],
                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


def child_environment(home):
    return {**os.environ, 'JM_HOME': str(home), 'JM_BUNDLE': str(BUNDLE),
            'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1',
            'PLAYWRIGHT_BROWSERS_PATH': str(BUNDLE / 'browser')}


def serve(home, port):
    import uvicorn
    from .web.app import create_app
    server = uvicorn.Server(uvicorn.Config(create_app(home), host='127.0.0.1', port=port, log_level='warning'))
    def watch_stop():
        while not (home / 'portable-stop').exists():
            time.sleep(.5)
        server.should_exit = True
    threading.Thread(target=watch_stop, daemon=True).start()
    server.run()


def run(home, open_browser=True):
    home.mkdir(parents=True, exist_ok=True)
    lock = InstanceLock(home)
    if not lock.acquire():
        lock.close()
        for _ in range(90):
            info = read_json(home / 'portable-running.json')
            if info.get('url') and health(info['url'], home):
                if open_browser:
                    open_ui(info['url'], home)
                return
            time.sleep(1)
        raise RuntimeError('工作台启动尚未完成，请打开“环境检查”查看日志')
    child = connector = None
    try:
        (home / 'portable-stop').unlink(missing_ok=True)
        ports = read_json(home / 'portable-ports.json')
        # Choose ports only for a new installation. A later collision must not silently invalidate jobs.
        if not ports:
            app_port = free_port(8776)
            ports = {'app': app_port, 'sau': free_port(5419, [app_port])}
            atomic_json(home / 'portable-ports.json', ports)
        values = configure(home)
        port = ports['app']
        if free_port(port) != port:
            port = free_port(8776, [ports['sau']])
            ports['app'] = port
            atomic_json(home / 'portable-ports.json', ports)
        url = f'http://127.0.0.1:{port}'
        atomic_json(home / 'portable-running.json', {'url': url, 'pid': os.getpid(), 'bundle': str(BUNDLE)})
        env = child_environment(home)
        env['JM_SAU_TOKEN'] = __import__('secrets').token_urlsafe(32)
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        python = str(Path(sys.executable).with_name('python.exe')) if os.name == 'nt' else sys.executable
        opened = False
        failures = 0
        with (home / 'portable.log').open('ab', buffering=0) as log:
            while not (home / 'portable-stop').exists():
                if child is None or child.poll() is not None:
                    if child is not None:
                        failures += 1
                        if failures >= 5:
                            raise RuntimeError('工作台连续启动失败，请打开“环境检查”查看日志')
                        time.sleep(2)
                    child = subprocess.Popen([python, '-B', '-m', 'jm_workbench.portable', 'serve', '--home', str(home), '--port', str(port)],
                                             env=env, cwd=home, stdout=log, stderr=log, creationflags=flags)
                    atomic_json(home / 'portable-running.json', {'url': url, 'pid': os.getpid(), 'child_pid': child.pid, 'bundle': str(BUNDLE)})
                if connector is None or connector.poll() is not None:
                    # The connector fails closed on an occupied port. Never kill or adopt another service.
                    if free_port(ports['sau']) == ports['sau']:
                        connector = subprocess.Popen([python, '-B', '-m', 'jm_workbench.portable_sau', '--home', str(home), '--port', str(ports['sau'])],
                                                     env=env, cwd=home, stdout=log, stderr=log, creationflags=flags)
                if not opened and health(url, home):
                    if open_browser:
                        open_ui(url + '/#community', home)
                    opened = True
                    failures = 0
                time.sleep(1)
    finally:
        (home / 'portable-stop').touch()
        for process in (child, connector):
            if process and process.poll() is None:
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=10)
        (home / 'portable-running.json').unlink(missing_ok=True)
        lock.close()


def diagnostics(home):
    import html
    from importlib.metadata import version
    from .core.config import revision
    results = [('Python', sys.version.split()[0]), ('系统', sys.platform), ('程序版本', revision()), ('数据目录', str(home))]
    for name in ('fastapi', 'uvicorn', 'pydantic', 'playwright', 'opencv-python-headless', 'flask', 'patchright'):
        try:
            results.append((name, version(name)))
        except Exception:
            results.append((name, '缺失，请重新完整解压'))
    try:
        results.append(('浏览器', str(browser_path())))
    except RuntimeError as ex:
        results.append(('浏览器', str(ex)))
    info = read_json(home / 'portable-running.json')
    results.append(('服务', '运行正常' if info.get('url') and health(info['url'], home) else '尚未启动或已退出'))
    results.append(('日志位置', str(home / 'portable.log')))
    path = home / '环境检查.html'
    path.write_text('<!doctype html><meta charset="utf-8"><title>JM环境检查</title><h1>JM工作台环境检查</h1><p>此页不包含账号、密钥和业务内容。</p><table>' + ''.join('<tr><th>'+html.escape(k)+'</th><td>'+html.escape(v)+'</td></tr>' for k,v in results) + '</table>', encoding='utf-8')
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['start', 'stop', 'diagnostics', 'serve'], nargs='?', default='start')
    parser.add_argument('--home', type=Path)
    parser.add_argument('--port', type=int, default=8776)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    args.no_browser = args.no_browser or os.environ.get('JM_NO_BROWSER') == '1'
    home = (args.home or default_home()).resolve()
    home.mkdir(parents=True, exist_ok=True)
    os.environ.update(child_environment(home))
    if args.command == 'serve':
        serve(home, args.port)
    elif args.command == 'stop':
        (home / 'portable-stop').touch()
    elif args.command == 'diagnostics':
        path = diagnostics(home)
        if not args.no_browser:
            open_ui(path.as_uri(), home)
    else:
        run(home, not args.no_browser)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        import traceback
        traceback.print_exc()
        if os.name == 'nt' and '--no-browser' not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(error), 'JM工作台未能启动', 0x10)
        sys.exit(1)
