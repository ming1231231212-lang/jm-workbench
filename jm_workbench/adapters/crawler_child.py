"""External runtime bridge; no upstream source or credentials are distributed with JM."""
import asyncio
import importlib
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse


class GuardStop(BaseException):
    pass


class LimitReached(BaseException):
    pass


class LoginRequired(BaseException):
    pass


def response_risk(status, data):
    if status in (401, 403, 412, 418, 429, 461, 471):
        return f'平台返回 HTTP {status}，任务已停止'
    if isinstance(data, dict):
        message = ' '.join(str(data.get(k, '')) for k in ('msg', 'message', 'error_msg', 'errors'))
        if any(w in message.lower() for w in ('captcha', 'verify', '频繁', '验证码', '验证失败', '访问受限', '封禁', '风控', '滑块', '账号异常')):
            return '平台要求验证或限制访问，任务已停止'
        if data.get('result') in (2, 50, 400002, 400001) or data.get('code') in (-100, 300012, -102):
            return '平台返回访问限制状态，任务已停止'
    return ''


async def check_challenge(page):
    text = await page.locator('body').inner_text(timeout=5000)
    if any(word in text for word in ('操作频繁', '访问过于频繁', '请通过验证', '拖动滑块', '完成安全验证', '账号异常', '账号被封禁', '访问受限', '网络环境存在风险')):
        raise GuardStop('页面要求安全验证或限制访问，停止同平台任务')
    if await page.locator('iframe[src*="captcha"], iframe[src*="verify"], #captcha-verify-image').count():
        raise GuardStop('页面出现安全验证，停止同平台任务')


async def execute(p):
    sys.path.insert(0, p['root'])
    import config
    overrides = dict(PLATFORM=p['platform'], KEYWORDS=p['keyword'], CRAWLER_TYPE='search', START_PAGE=1,
        ENABLE_CDP_MODE=True, CDP_CONNECT_EXISTING=True, AUTO_CLOSE_BROWSER=False,
        COOKIES='', ENABLE_IP_PROXY=False, MAX_CONCURRENCY_NUM=1, CRAWLER_MAX_NOTES_COUNT=p['max_items'],
        CRAWLER_MAX_SLEEP_SEC=5, ENABLE_GET_COMMENTS=p['collect_comments'],
        CRAWLER_MAX_COMMENTS_COUNT_SINGLENOTES=p['comments_per_item'], ENABLE_GET_SUB_COMMENTS=False,
        ENABLE_GET_COMMENTER_PROFILE=False, ENABLE_GET_MEIDAS=False, ENABLE_GET_WORDCLOUD=False,
        SAVE_DATA_OPTION='jsonl', SAVE_DATA_PATH=p['output'], HEADLESS=False)
    for k, v in overrides.items():
        setattr(config, k, v)
    # The local legacy fork auto-loads fix_cookies.json. This process must keep
    # the selected browser's identity, so exclude that one optional input.
    original_exists = os.path.exists
    cookie_override = Path(p['root']) / 'fix_cookies.json'
    def scoped_exists(path):
        if isinstance(path, (str, bytes, os.PathLike)):
            try:
                if Path(path).resolve() == cookie_override.resolve():
                    return False
            except (TypeError, ValueError):
                pass
        return original_exists(path)
    os.path.exists = scoped_exists
    import httpx
    from playwright.async_api import BrowserContext, Page
    from tools.cdp_browser import CDPBrowserManager
    from tools.async_file_writer import AsyncFileWriter
    captured, contexts = [], []
    counts, last_request, request_count = {}, 0., 0
    page_risk = []
    platform_domain = {'ks':'kuaishou.com','dy':'douyin.com','xhs':'xiaohongshu.com',
                       'bili':'bilibili.com','wb':'weibo.com','tieba':'baidu.com','zhihu':'zhihu.com'}[p['platform']]
    original_request = httpx.AsyncClient.request
    original_init = httpx.AsyncClient.__init__

    def client_init(self, *args, **kwargs):
        if kwargs.get('proxy') or kwargs.get('proxies'):
            raise GuardStop('爬虫请求尝试使用独立代理，已停止')
        kwargs['trust_env'] = False
        original_init(self, *args, **kwargs)

    async def guarded_request(self, method, url, **kwargs):
        nonlocal last_request, request_count
        if page_risk:
            raise GuardStop(page_risk[0])
        for context in contexts:
            pages = [page for page in context.pages if (urlparse(page.url).hostname or '').endswith('.'+platform_domain) or urlparse(page.url).hostname == platform_domain]
            if pages:
                await check_challenge(pages[-1])
        request_count += 1
        if request_count > 40:
            raise LimitReached('已达到单批请求上限')
        await asyncio.sleep(max(0, 5 - (time.monotonic() - last_request)))
        last_request = time.monotonic()
        kwargs['timeout'] = 20
        try:
            response = await original_request(self, method, url, **kwargs)
        except Exception:
            raise LoginRequired('平台读取未成功，已停止且不会自动重试')
        try:
            data = response.json()
        except (ValueError, UnicodeError):
            data = None
        reason = response_risk(response.status_code, data)
        if reason:
            raise GuardStop(reason)
        if response.status_code >= 400:
            raise LoginRequired('平台接口读取失败，请检查账号及接口适配')
        return response

    async def existing(self, playwright, *args, **kwargs):
        # Do not use upstream launch code that may inject stealth settings or other cookies.
        self.browser = await playwright.chromium.connect_over_cdp(p['endpoint'], timeout=30000)
        if not self.browser.contexts:
            raise LoginRequired('账号浏览器没有可用窗口')
        self.browser_context = self.browser.contexts[0]
        def watch(response):
            host = urlparse(response.url).hostname or ''
            if (host == platform_domain or host.endswith('.'+platform_domain)) and response.request.resource_type in ('document','xhr','fetch'):
                reason = response_risk(response.status, {})
                if reason:
                    page_risk.append(reason)
        self.browser_context.on('response', watch)
        contexts.append(self.browser_context)
        return self.browser_context

    async def preserve(self, *args, **kwargs):
        # async_playwright's exit disconnects; never close a user's context or browser.
        return None

    async def no_cookie_swap(self, *args, **kwargs):
        raise LoginRequired('请在账号浏览器完成登录；不导入其他来源Cookie')

    async def manual_login(self, *args, **kwargs):
        if getattr(self, 'context_page', None):
            await check_challenge(self.context_page)
        raise LoginRequired('平台登录尚未有效，请在该账号浏览器登录后重新检查')

    async def capture(self, item, item_type):
        kind = 'comments' if 'comment' in item_type else 'contents'
        cap = p['max_items'] * p['comments_per_item'] if kind == 'comments' else p['max_items']
        if counts.get(kind, 0) >= cap:
            return
        counts[kind] = counts.get(kind, 0) + 1
        captured.append({'record_type': kind, **item})

    httpx.AsyncClient.__init__ = client_init
    httpx.AsyncClient.request = guarded_request
    CDPBrowserManager.launch_and_connect = existing
    CDPBrowserManager.cleanup = preserve
    BrowserContext.add_cookies = no_cookie_swap
    AsyncFileWriter.write_to_jsonl = capture
    login = importlib.import_module('media_platform.' + {'ks': 'kuaishou', 'dy': 'douyin', 'xhs': 'xhs',
        'bili': 'bilibili', 'wb': 'weibo', 'tieba': 'tieba', 'zhihu': 'zhihu'}[p['platform']] + '.login')
    for value in vars(login).values():
        if isinstance(value, type) and value.__module__ == login.__name__ and hasattr(value, 'begin'):
            value.begin = manual_login
    from main import CrawlerFactory
    if p.get('probe'):
        return {'state': 'completed', 'message': '依赖导入检查通过', 'items': [],
                'platforms': list(CrawlerFactory.CRAWLERS), 'guarded': True}
    state, message = 'completed', '本批读取完成'
    try:
        crawler = CrawlerFactory.create_crawler(p['platform'])
        await crawler.start()
    except LimitReached as ex:
        message = str(ex)
    except GuardStop as ex:
        state, message = 'risk', str(ex)
    except LoginRequired as ex:
        state, message = 'failed', str(ex)
    except BaseException as ex:
        state, message = 'failed', '爬虫未完成：' + type(ex).__name__ + '；请检查登录状态和适配器'
    return {'state': state, 'message': message, 'items': captured, 'counts': counts, 'requests': request_count}


if __name__ == '__main__':
    params = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    try:
        result = asyncio.run(execute(params))
    except BaseException as ex:
        result = {'state': 'failed', 'message': '外部爬虫依赖或启动失败：' + type(ex).__name__, 'items': []}
    (Path(params['output']) / 'result.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
