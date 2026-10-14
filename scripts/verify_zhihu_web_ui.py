"""Local-only browser acceptance: fake adapter, no external requests or real account."""
import json
import socket
import threading
import time
import tempfile
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright, expect

from jm_workbench.community.models import CommunityAccount
from jm_workbench.web.app import create_app


def main():
    out = Path(__file__).resolve().parents[1] / 'outputs' / 'zhihu-integration-20261014' / 'ui-test'
    out.mkdir(parents=True, exist_ok=True)
    class Fake:
        opened = []
        def check(self, *args): raise AssertionError('automatic account check forbidden')
        def publish(self, *args): raise AssertionError('real publication forbidden')
        def open(self, account, url):
            self.opened.append(url)
            return {'message': 'isolated webpage handoff'}
    fake = Fake()
    sandbox = tempfile.TemporaryDirectory(prefix='fixture-', dir=out)
    assert Path(sandbox.name).resolve().is_relative_to(out.resolve())
    app = create_app(Path(sandbox.name), worker=False, community_adapter=fake)
    s = app.state.community
    s.cfg.config.save({'community_browser_execution': 'web'})
    account = s.save_account(CommunityAccount(platform='zhihu', name='知乎隔离测试账号'))
    s.save_account(CommunityAccount(platform='quora', name='未接入评论账号'))
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); sock.listen(16)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='warning'))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    for _ in range(100):
        if server.started: break
        time.sleep(.05)
    checks, errors, external = [], [], []
    base = f'http://127.0.0.1:{port}'
    def check(name, condition=True):
        assert condition, name
        checks.append(name)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width':1440, 'height':1000}, accept_downloads=True)
            def route(r):
                if not r.request.url.startswith(base + '/'):
                    external.append(r.request.url); r.abort()
                else: r.continue_()
            context.route('**/*', route)
            page = context.new_page(); page.set_default_timeout(10000)
            page.on('pageerror', lambda error: errors.append(str(error)))
            def click(action, scope=''):
                page.locator(f'{scope} [data-action="{action}"]' if scope else f'[data-action="{action}"]').first.click()
                expect(page.locator('body')).to_have_attribute('aria-busy', 'false')
            page.goto(base + '/#community/accounts')
            expect(page.get_by_role('button', name='添加知乎', exact=True)).to_be_visible()
            check('Zhihu shortcut visible')
            page.locator('[data-action="com-v2-account-mode"][data-id="matrix"]').click()
            expect(page.locator('.matrix')).to_contain_text('评论：网页发布；每日计划：不可用')
            check('matrix separates web comments and daily automation')
            page.goto(base + '/#community/content')
            click('com-v2-compose'); click('com-new')
            form = page.locator('#com-post-form')
            form.locator(f'[name="account_ids"][value="{account["id"]}"]').check()
            form.locator('[name="title"]').fill('知乎文章隔离验收')
            body = '这是本机隔离测试正文，包含 <script>不应执行</script>，不会发送到真实知乎。'
            form.locator('[name="body"]').fill(body)
            check('article has no invented board field', form.locator('[name^="destination_"]').count() == 0)
            form.locator('button[value="draft"]').click()
            expect(page.locator('#dialog')).not_to_be_visible()
            article = next(p for p in s.state()['posts'] if p['payload']['kind'] == 'thread')
            check('draft save creates no publication job', not article['jobs'])
            page.get_by_role('button', name='知乎文章隔离验收', exact=True).click()
            expect(page.locator('.article-preview')).to_have_text(body)
            check('full body rendered safely', page.locator('.article-preview script').count() == 0)
            page.locator('.content-export summary').click()
            with page.expect_download() as download:
                page.get_by_role('link', name='下载正文', exact=True).click()
            downloaded = download.value
            downloaded.save_as(out / 'article-export.md')
            check('download preserves exact article body', body in (out / 'article-export.md').read_text(encoding='utf-8'))
            click('com-launch', '#community-drawer')
            expect(page.locator('#community-drawer')).to_contain_text('待网页发布')
            click('com-open-job', '#community-drawer')
            check('article opens native editor handoff', fake.opened == ['https://zhuanlan.zhihu.com/write'])
            click('com-v2-close')
            click('com-v2-compose'); click('com-new-reply')
            form = page.locator('#com-post-form')
            check('unsupported platform excluded from comments', form.locator(f'[name="account_ids"][value="{account["id"]}"]').count() == 1 and form.locator('[name="account_ids"]').count() == 1)
            form.locator(f'[name="account_ids"][value="{account["id"]}"]').check()
            form.locator('[name="title"]').fill('知乎评论隔离验收')
            reply = '针对这篇原帖的具体问题，建议使用可复现的小样本并记录实际结果。'
            target = 'https://zhuanlan.zhihu.com/p/624717941'
            form.locator('[name="body"]').fill(reply)
            form.locator('[name^="destination_"]').fill(target + '?utm_source=fixture')
            form.locator('button[value="launch"]').click()
            expect(page.locator('#dialog')).not_to_be_visible()
            comment = next(p for p in s.state()['posts'] if p['payload']['kind'] == 'reply')
            check('comment creates exactly one manual job', len(comment['jobs']) == 1 and comment['jobs'][0]['state'] == 'manual')
            page.get_by_role('button', name='知乎评论隔离验收', exact=True).click()
            expect(page.locator('.article-preview')).to_have_text(reply)
            expect(page.locator('#community-drawer')).to_contain_text(target)
            click('com-open-job', '#community-drawer')
            check('comment opens canonical original post', fake.opened[-1] == target)
            click('com-record', '#community-drawer')
            page.locator('#com-record-form [name="url"]').fill('https://zhuanlan.zhihu.com/p/624717942')
            page.locator('#com-record-form button.primary').click()
            expect(page.locator('#toast')).to_contain_text('原帖')
            check('wrong result target leaves job manual', s.jobs(comment['id'])[0]['state'] == 'manual')
            page.locator('#com-record-form [name="url"]').fill(target)
            page.locator('#com-record-form button.primary').click()
            expect(page.locator('#dialog')).not_to_be_visible()
            expect(page.locator('#community-drawer')).to_contain_text('已登记 · 待核验')
            check('record retains unverified public visibility', s.jobs(comment['id'])[0]['receipt']['visibility'] == 'user_reported')
            click('com-v2-close')
            page.screenshot(path=str(out / 'content-desktop.png'), full_page=True)
            page.set_viewport_size({'width':390, 'height':844})
            page.goto(base + '/#community/accounts')
            expect(page.get_by_role('button', name='添加知乎', exact=True)).to_be_visible()
            check('mobile view has no document overflow', page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            check('no JavaScript errors', not errors)
            check('no external website requests', not external)
            browser.close()
    finally:
        server.should_exit = True; thread.join(5)
        sandbox.cleanup()
        result = {'checks': checks, 'count': len(checks), 'errors': errors, 'external_requests': external, 'real_publications': 0}
        (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
