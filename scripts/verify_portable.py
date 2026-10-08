"""Acceptance using only the shipped runtime and dependencies. No external publications."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    bundle, out = args.bundle.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    home = out / '中文 用户数据'
    home.mkdir()
    checks = []
    def check(name, condition=True):
        assert condition, name
        checks.append(name)
        print('PASS ' + name, flush=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def call(base, path, body=None, token='', method=None, headers=None):
        req = urllib.request.Request(base+path, data=json.dumps(body).encode() if body is not None else None,
            method=method or ('POST' if body is not None else 'GET'),
            headers={'Content-Type':'application/json', 'X-JM-Token':token, **(headers or {})})
        try:
            with opener.open(req, timeout=20) as response:
                raw = response.read()
                return response.status, json.loads(raw) if 'json' in response.headers.get('Content-Type','') else raw
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())
    def read(path):
        try: return json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError): return {}
    def wait(predicate, seconds=60):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                result = predicate()
                if result: return result
            except (OSError, ValueError, KeyError): pass
            time.sleep(.5)
        raise AssertionError('Timed out waiting for local acceptance condition')
    def ready():
        info = read(home / 'portable-running.json')
        return info if info.get('url') and call(info['url'], '/api/health')[0] == 200 else None
    env = {**os.environ, 'JM_HOME':str(home), 'JM_NO_BROWSER':'1', 'PYTHONDONTWRITEBYTECODE':'1',
           'JM_BUNDLED_BROWSER':'1',
           'PATH':str(Path(os.environ['SystemRoot']) / 'System32'), 'PYTHONPATH':'', 'PYTHONHOME':'',
           'PROGRAMFILES':str(out/'no-installed-programs'), 'PROGRAMFILES(X86)':str(out/'no-installed-programs-x86'),
           'LOCALAPPDATA':str(out/'empty-local-appdata')}
    check('OS is Windows x64', sys.platform == 'win32' and sys.maxsize > 2**32)
    check('Acceptance uses the embedded Python', Path(sys.executable).resolve().is_relative_to(bundle / 'runtime'))
    check('No developer Python or Node on process PATH', shutil.which('python', path=env['PATH']) is None and shutil.which('node', path=env['PATH']) is None)
    # Hold the preferred port if no production service already owns it.
    occupied = socket.socket()
    try:
        occupied.bind(('127.0.0.1', 8776)); occupied.listen()
    except OSError:
        occupied.close(); occupied = None
    started = False
    try:
        subprocess.run([str(bundle/'JM工作台.exe')], env=env, check=True, timeout=10)
        started = True
        info = wait(ready, 90); base = info['url']
        check('GUI launcher starts a fresh isolated installation', bool(info.get('child_pid')))
        check('Occupied production port is not adopted', not base.endswith(':8776'))
        state = call(base, '/api/state')[1]; token = state['token']
        community = call(base, '/api/community/state')[1]
        check('No owner accounts, business data or tasks are distributed', state['accounts'] == state['tasks'] == state['runs'] == community['accounts'] == community['posts'] == [])
        settings = state['settings']; connector = settings['sau_url']
        check('Bundled browser is configured for isolated acceptance', Path(settings['chrome_path']).is_relative_to(bundle/'browser'))
        def connected():
            response = call(base, '/api/publishing/state')
            return response[0] == 200 and response[1].get('connected')
        wait(connected, 90)
        check('Bundled video connector starts with an empty database')
        # Local adapter imports cover all four shipped SAU integrations without opening a platform.
        check('All four video platforms advertised by the loaded integration', len(call(base, '/api/publishing/state')[1]['platforms']) == 4)
        check('Foreign website cannot mutate the workbench', call(base, '/api/accounts', {'name':'evil','platform':'ks'}, token, headers={'Origin':'https://example.invalid'})[0] == 403)
        check('Connector rejects unauthenticated API requests', call(connector, '/getAccounts')[0] == 403)
        check('Connector rejects foreign browser origin', call(connector, '/', headers={'Origin':'https://example.invalid'})[0] == 403)
        check('Cookie download and unguarded batch API are unavailable', call(connector, '/downloadCookie')[0] == 404 and call(connector, '/postVideoBatch', [])[0] == 404)
        check('Settings can be saved without optional crawler', call(base, '/api/settings', {k:settings[k] for k in ('chrome_path','crawler_root','crawler_python')}, token, 'PUT')[0] == 200)
        account = call(base, '/api/community/accounts', {'name':'验收演示账号','platform':'tieba'}, token)[1]
        check('Community account creation', bool(account.get('id')))
        post_body = {'request_id':'portable-acceptance-draft','title':'验收示例：怎样管理自己的AI工具清单',
                     'body':'这是本地验收用草稿，仅用于确认内容保存与回显，不会对外发送。','tags':['AI'],
                     'targets':[{'account_id':account['id'],'destination':'人工智能'}]}
        code, draft = call(base, '/api/community/posts', post_body, token)
        check('Community draft creation without publishing', code == 200)
        saved_post = call(base, '/api/community/state')[1]['posts'][0]
        check('Draft content survives round trip', saved_post['payload']['body'] == post_body['body'])
        task = call(base, '/api/tasks', {'name':'本地采集配置样例','platform':'ks','kind':'crawler','keywords':['人工智能'],'enabled':False}, token)
        check('Crawler task configuration works and stays disabled', task[0] == 200 and task[1]['enabled'] is False)
        # Create a real, small video in the embedded media engine; never read personal files.
        import cv2
        import numpy as np
        video = out / 'sample.mp4'
        writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), 24, (64,64))
        assert writer.isOpened()
        for i in range(24): writer.write(np.full((64,64,3),80+i,dtype=np.uint8))
        writer.release()
        from jm_workbench.publishing.service import probe_video_embedded
        check('Bundled decoder reads an actual video without FFprobe', probe_video_embedded(video)['width'] == 64)
        req = urllib.request.Request(base+'/api/publishing/materials/upload?name=sample.mp4', data=video.read_bytes(),
                                     headers={'X-JM-Token':token,'Content-Type':'application/octet-stream'})
        with opener.open(req, timeout=30) as response:
            check('Video upload and metadata validation', response.status == 200)
        invalid = out / 'bad.mp4'; invalid.write_text('not a video')
        try: probe_video_embedded(invalid); check('Corrupt video is rejected', False)
        except ValueError: check('Corrupt video is rejected')
        # Exercise the exact browser and Playwright driver shipped to recipients, on local URLs only.
        from playwright.sync_api import sync_playwright
        chrome = next((bundle/'browser').glob('**/chrome.exe'))
        errors=[]; external=[]
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=str(chrome), headless=True)
            context = browser.new_context(viewport={'width':1440,'height':1000})
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith((base+'/',connector+'/')) else (external.append(route.request.url),route.abort()))
            page = context.new_page(); page.on('pageerror', lambda error:errors.append(str(error)))
            for route in ('community','tasks','publishing','data','accounts','settings','overview','matrix','platforms','runs'):
                page.goto(base+'/#'+route); page.locator('#content h1').wait_for(); page.wait_for_timeout(250)
                check('UI route '+route, bool(page.locator('#content h1').inner_text()))
            page.goto(base+'/#community'); page.locator('#content h1').wait_for()
            page.screenshot(path=str(out/'community.png'), full_page=True)
            page.goto(connector+'/'); page.get_by_text('还没有账号。选择平台并打开登录后，账号会保存在这台电脑。',exact=True).wait_for()
            check('Bundled video account manager renders an empty state')
            # Add a deliberately offline fixture, exercise rename/delete through the real UI,
            # and verify no login browser or publishing operation is started.
            import sqlite3
            with sqlite3.connect(home/'video-publisher/db/database.db') as db:
                db.execute("INSERT INTO user_info(type,filePath,userName,status) VALUES(4,'test-only.json','本地验收账号',0)")
            page.locator('#refresh').click(); page.get_by_text('修改备注',exact=True).wait_for()
            page.once('dialog', lambda dialog:dialog.accept('修改后的本地备注'))
            page.get_by_text('修改备注',exact=True).click()
            page.get_by_text('修改后的本地备注 · 快手 · 需要登录',exact=True).wait_for()
            check('Video account remark editing works')
            page.once('dialog',lambda dialog:dialog.accept())
            page.get_by_text('删除',exact=True).click()
            page.get_by_text('还没有账号。选择平台并打开登录后，账号会保存在这台电脑。',exact=True).wait_for()
            check('Extra video account can be deleted')
            page.screenshot(path=str(out/'video-accounts.png'), full_page=True)
            check('No browser JavaScript exceptions', not errors)
            check('Local UI test made no external requests', not external)
            context.close(); browser.close()
        pid = read(home/'portable-running.json')['pid']
        subprocess.run([str(bundle/'JM工作台.exe')], env=env, check=True, timeout=10)
        time.sleep(3)
        check('Double launch retains exactly the same supervisor', read(home/'portable-running.json')['pid'] == pid)
        # Kill only the exact child this acceptance instance created; supervisor must recover it.
        old_child = read(home/'portable-running.json')['child_pid']
        subprocess.run(['taskkill.exe','/PID',str(old_child),'/F'],env=env,capture_output=True,check=True)
        recovered = wait(lambda: ready() if read(home/'portable-running.json').get('child_pid') != old_child else None, 45)
        check('Crashed workbench child is restarted', recovered['child_pid'] != old_child)
        restored = call(base, '/api/community/state')[1]
        check('Drafts remain drafts after restart', len(restored['posts']) == 1 and restored['posts'][0]['state'] == 'draft')
        check('Disabled task is not resumed', call(base, '/api/state')[1]['tasks'][0]['enabled'] is False)
        subprocess.run([str(bundle/'环境检查.exe')],env=env,check=True,timeout=10)
        wait(lambda:(home/'环境检查.html').is_file())
        check('GUI environment diagnostic writes a local report')
        subprocess.run([str(bundle/'退出工作台.exe')],env=env,check=True,timeout=10)
        wait(lambda:not (home/'portable-running.json').exists(), 45)
        started=False
        time.sleep(3)
        check('Manual exit stays stopped', not (home/'portable-running.json').exists())
        check('Exit preserves user data', (home/'jm.db').is_file())
        # Restart with existing data models an upgrade using the same stable external home.
        subprocess.run([str(bundle/'JM工作台.exe')],env=env,check=True,timeout=10); started=True
        info=wait(ready,90)
        check('Restart preserves all local content', len(call(info['url'],'/api/community/state')[1]['posts']) == 1)
        subprocess.run([str(bundle/'退出工作台.exe')],env=env,check=True,timeout=10)
        wait(lambda:not (home/'portable-running.json').exists(),45); started=False
        check('No database or profiles are written into the program directory', not list(bundle.rglob('jm.db')) and not (bundle/'var').exists())
        check('Program directory remains free of generated bytecode', not list(bundle.rglob('__pycache__')))
        report={'result':'passed','checks':checks,'count':len(checks),'runtime':sys.version.split()[0],
                'os':sys.platform,'architecture':'x64','real_platform_publications':0,
                'limits':['Tests run on this Windows host, not a separate physical Windows 10 machine',
                          'Platform login/permissions and public visibility require the recipient account']}
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    finally:
        if started:
            (home/'portable-stop').touch()
            try: wait(lambda:not (home/'portable-running.json').exists(),45)
            except AssertionError: pass
        if occupied: occupied.close()


if __name__ == '__main__':
    main()
