"""Juejin native website adapter. No direct write API, one guarded submit only."""
import json
import re
import time
from datetime import datetime
from urllib.parse import quote, urlparse

from .adapters import NotSubmitted, PreflightStopped
from .registry import destination, juejin_thread_url, tag_label
from ..adapters.chrome import endpoint

ARTICLE_WRITE = '/content_api/v1/article/publish'
COMMENT_WRITE = '/interact_api/v1/comment/publish'


def validate_payload(payload, target):
    body = payload['body']
    if not re.search(r'AI\s*辅助', body, re.I):
        raise ValueError('掘金内容需明确标注AI辅助整理')
    if re.search(r'https?://|www\.|加[微Vv]|私信|加群|返佣|代充|购买链接', body, re.I):
        raise ValueError('掘金自动发布内容不得含营销外链、联系方式或导流话术')
    if payload.get('kind') == 'reply':
        juejin_thread_url(target)
        if not 20 <= len(body) <= 1000:
            raise ValueError('掘金评论需20–1000字')
    else:
        destination('juejin', target)
        if payload.get('category') and payload['category'] != target:
            raise ValueError('文章分类与发布目标不一致')
        if not payload.get('platform_tags'):
            raise ValueError('请为掘金文章选择相关标签')
        for tag in payload['platform_tags']:
            tag_label(tag)
        if not 5 <= len(payload['title']) <= 100 or not 200 <= len(body) <= 12000:
            raise ValueError('掘金文章标题需5–100字，正文需200–12000字')


def identity(page):
    if urlparse(page.url).hostname != 'juejin.cn':
        raise PreflightStopped('掘金页面跳转，尚未提交')
    avatar = page.locator('header .avatar-wrapper')
    try:
        avatar.wait_for(state='visible', timeout=10000)
        links = page.locator('header .nav-item.menu a[href*="/user/"]')
        if not links.count():
            avatar.click(timeout=5000)
        hrefs = links.evaluate_all('(xs)=>xs.map(x=>x.getAttribute("href"))')
        ids = {m.group(1) for h in hrefs if (m := re.fullmatch(r'/user/([1-9][0-9]+)(?:/posts)?', h))}
        if len(ids) != 1:
            raise ValueError('ambiguous identity')
        return ids.pop()
    except Exception:
        raise PreflightStopped('掘金账号未登录或身份无法核验，请在此账号Chrome完成登录') from None


def safety_check(page):
    for selector in ('iframe[src*="captcha"]', 'iframe[src*="verify"]', '.captcha_verify_container', '.geetest_panel'):
        visible = page.locator(selector + ':visible')
        if visible.count():
            raise NotSubmitted('掘金要求安全验证，已停止；请到网站处理')


def read_article(page):
    url = juejin_thread_url(page.url)
    page.locator('article h1.article-title').wait_for(timeout=8000)
    title = page.locator('article h1.article-title').inner_text().strip()
    body = page.locator('#article-root').inner_text().strip()
    href = page.locator('article .author-info-block a[href*="/user/"]').first.get_attribute('href')
    author = re.search(r'/user/([1-9][0-9]+)', href or '')
    created = page.locator('article time[datetime]').get_attribute('datetime')
    if not title or not body or not author or not created:
        raise PreflightStopped('文章原文或作者不可核验，未提交')
    tags = page.locator('.tag-list a[href*="/tag/"], .tag-list-box a[href*="/tag/"]').all_text_contents()
    return {'url': url, 'title': title[:200], 'excerpt': body[:6000],
            'author_id': author.group(1), 'created': datetime.fromisoformat(created.replace('Z', '+00:00')).timestamp(),
            'tags': [t.strip() for t in tags]}


def receipt(data, kind, target):
    if not isinstance(data, dict):
        raise RuntimeError('掘金回执格式不明')
    if 'err_no' not in data:
        raise RuntimeError('掘金回执缺少结果码')
    if str(data['err_no']) != '0':
        raise NotSubmitted('掘金拒绝提交或要求安全验证，已停止；请在网站查看原因')
    inner = data.get('data') or {}
    if kind == 'reply':
        info = inner.get('comment_info') or inner
        ident = str(info.get('comment_id') or '')
        if info.get('item_id') and str(info['item_id']) != juejin_thread_url(target).rsplit('/', 1)[-1]:
            raise RuntimeError('掘金评论回执目标不一致')
        url = juejin_thread_url(target)
    else:
        ident = str(inner.get('article_id') or (inner.get('article_info') or {}).get('article_id') or '')
        url = 'https://juejin.cn/post/' + ident
    if not re.fullmatch(r'[1-9][0-9]{10,23}', ident):
        raise RuntimeError('掘金缺少明确内容编号，禁止重发')
    result = {'post_id': ident, 'url': url, 'visibility': 'unverified'}
    if kind == 'reply':
        result.update(comment_id=ident, thread_id=url.rsplit('/', 1)[-1])
    return result


class SubmitGuard:
    def __init__(self, kind, payload, target, draft=''):
        self.kind, self.payload, self.target, self.draft = kind, payload, target, draft
        self.count = 0
        self.blocked = False

    def valid(self, data):
        if self.kind == 'reply':
            return (str(data.get('item_id')) == self.target.rsplit('/', 1)[-1] and data.get('item_type') == 2 and
                    data.get('comment_content') == self.payload['body'] and not data.get('comment_pics') and
                    not any(data.get(k) for k in ('reply_id', 'reply_comment_id', 'reply_to_reply_id', 'reply_to_author_id')))
        return str(data.get('draft_id', '')) == self.draft

    def route(self, route):
        if route.request.method != 'POST':
            return route.fallback()
        self.count += 1
        try:
            valid = self.valid(json.loads(route.request.post_data or '{}'))
        except Exception:
            valid = False
        if self.count != 1 or not valid:
            self.blocked = True
            return route.abort('blockedbyclient')
        route.fallback()


def submit_once(page, button, payload, target, draft=''):
    kind = payload.get('kind', 'thread')
    path = COMMENT_WRITE if kind == 'reply' else ARTICLE_WRITE
    guard = SubmitGuard(kind, payload, target, draft)
    page.route('**' + path + '*', guard.route)
    if not button.is_enabled():
        raise PreflightStopped('提交按钮不可用，尚未提交')
    # Any exception after this point is unknown. The caller closes this owned page.
    with page.expect_response(lambda r: urlparse(r.url).hostname == 'api.juejin.cn' and
                              urlparse(r.url).path == path and r.request.method == 'POST', timeout=25000) as waiting:
        button.press('Enter', timeout=5000)
    response = waiting.value
    if guard.blocked or guard.count != 1:
        raise RuntimeError('提交请求核对失败，停止核实')
    if response.status in (400, 401, 403, 422, 429):
        raise NotSubmitted('掘金拒绝请求，已暂停此平台')
    if not response.ok:
        raise RuntimeError('掘金提交结果不明')
    try:
        data = response.json()
    except Exception:
        # Native article publishing navigates immediately and can discard the response body.
        if kind != 'thread':
            raise RuntimeError('掘金评论回执不可读，禁止重发') from None
        page.wait_for_url('https://juejin.cn/published*', timeout=8000)
        link = page.get_by_role('link', name='《' + payload['title'] + '》', exact=True)
        link.wait_for(timeout=5000)
        if '发布成功' not in page.locator('body').inner_text():
            raise RuntimeError('尚无明确发布结果')
        url = link.get_attribute('href') or ''
        m = re.fullmatch(r'(?:https://juejin.cn)?/spost/([1-9][0-9]{10,23})', url)
        if not m:
            raise RuntimeError('发布结果链接异常')
        return {'post_id': m.group(1), 'url': 'https://juejin.cn/post/' + m.group(1),
                'visibility': 'unverified', 'evidence': 'native_success_page'}
    return receipt(data, kind, target)


def prepare_reply(page, payload, expected, target):
    meta = read_article(page)
    if meta['url'] != target or meta['author_id'] == expected:
        raise PreflightStopped('目标变化或为本人文章，不自动评论')
    if not payload.get('source_title') or meta['title'] != payload['source_title']:
        raise PreflightStopped('原帖标题不一致，尚未提交')
    if not payload.get('source_excerpt') or not meta['excerpt'].startswith(payload['source_excerpt'].strip()):
        raise PreflightStopped('原帖正文发生变化，尚未提交')
    safety_check(page)
    editor = page.locator('.auth-card .rich-input[contenteditable="true"]:visible')
    editor.wait_for(timeout=8000)
    if editor.count() != 1 or editor.inner_text().strip():
        raise PreflightStopped('评论编辑器不唯一或已有内容，已保留')
    editor.fill(payload['body'])
    if editor.inner_text().strip() != payload['body']:
        raise PreflightStopped('评论正文不一致，未提交')
    if identity(page) != expected:
        raise PreflightStopped('掘金身份变化，未提交')
    safety_check(page)
    return page.locator('.auth-card .submit-btn:visible')


def prepare_article(page, payload, target):
    title = page.locator('input[placeholder="输入文章标题..."]')
    title.wait_for(timeout=10000)
    editor = page.locator('.CodeMirror')
    if title.input_value().strip() or editor.evaluate('(x)=>x.CodeMirror.getValue()').strip():
        raise PreflightStopped('文章编辑器已有内容，保留原稿并停止')
    title.fill(payload['title'])
    editor.click()
    page.keyboard.insert_text(payload['body'])
    if editor.evaluate('(x)=>x.CodeMirror.getValue()') != payload['body']:
        raise PreflightStopped('文章正文核对不一致')
    return configure_article(page, payload, target)


def configure_article(page, payload, target):
    title = page.locator('input[placeholder="输入文章标题..."]')
    editor = page.locator('.CodeMirror')
    if title.input_value() != payload['title'] or editor.evaluate('(x)=>x.CodeMirror.getValue()') != payload['body']:
        raise PreflightStopped('文章快照不一致，未选择发布设置')
    page.get_by_text('发布', exact=True).first.click(timeout=5000)
    category = page.locator('.category-list .item').filter(has_text=re.compile(r'^\s*' + re.escape(target) + r'\s*$'))
    category.click(timeout=5000)
    if category.get_attribute('class').split().count('active') != 1:
        raise PreflightStopped('文章分类没有正确选择')
    for tag in payload['platform_tags']:
        box = page.locator('input.byte-select__input').first
        if not box.is_visible():
            page.get_by_text('请搜索添加标签', exact=True).click(timeout=5000)
        box.fill(tag)
        option = page.locator('.byte-select-option:visible').filter(has_text=re.compile(r'^\s*' + re.escape(tag) + r'\s*$'))
        option.wait_for(timeout=7000)
        if option.count() != 1:
            raise PreflightStopped('没有找到唯一的对应标签，未提交')
        option.click(timeout=5000)
    page.locator('.summary-textarea textarea').fill(re.sub(r'[#\n]+', ' ', payload['body'])[:100])
    if title.input_value() != payload['title'] or editor.evaluate('(x)=>x.CodeMirror.getValue()') != payload['body']:
        raise PreflightStopped('提交前文章快照核对失败')
    safety_check(page)
    page.wait_for_url(re.compile(r'https://juejin.cn/editor/drafts/[1-9][0-9]+'), timeout=10000)
    return page.get_by_role('button', name='确定并发布', exact=True), page.url.rsplit('/', 1)[-1]


class JuejinBrowser:
    def run(self, account, payload, target):
        from playwright.sync_api import sync_playwright
        if payload:
            validate_payload(payload, target)
        try:
            ws = endpoint(account['profile_dir'])
        except Exception:
            raise PreflightStopped('掘金账号浏览器未连接，请先登录 / 打开') from None
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.connect_over_cdp(ws, timeout=10000)
            except Exception:
                raise PreflightStopped('掘金账号Chrome连接未完成') from None
            context = browser.contexts[0]
            home = context.new_page()
            page = None
            try:
                try:
                    home.goto('https://juejin.cn/', wait_until='domcontentloaded', timeout=20000)
                    actual = identity(home)
                except Exception:
                    raise PreflightStopped('掘金账号页面未就绪，尚未提交') from None
                if payload is None:
                    return actual
                if actual != account['identity']:
                    raise PreflightStopped('掘金登录身份变化，未提交')
                page = context.new_page()
                try:
                    page.goto(target if payload.get('kind') == 'reply' else 'https://juejin.cn/editor/drafts/new?v=2',
                              wait_until='domcontentloaded', timeout=20000)
                    if payload.get('kind') == 'reply':
                        button, draft = prepare_reply(page, payload, actual, target), ''
                    else:
                        button, draft = prepare_article(page, payload, target)
                        home.reload(wait_until='domcontentloaded', timeout=20000)
                        if identity(home) != actual:
                            raise PreflightStopped('文章提交前账号变化，未提交')
                except (NotSubmitted, PreflightStopped):
                    raise
                except Exception:
                    raise PreflightStopped('掘金编辑器或标签核对未完成，尚未提交') from None
                return submit_once(page, button, payload, target, draft)
            finally:
                if page is not None:
                    page.close()
                home.close()

    def discover(self, account, tags):
        from playwright.sync_api import sync_playwright
        for tag in tags:
            tag_label(tag)
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(endpoint(account['profile_dir']), timeout=10000)
            page = browser.contexts[0].new_page()
            result, links = [], []
            try:
                page.goto('https://juejin.cn/', wait_until='domcontentloaded', timeout=20000)
                if identity(page) != account['identity']:
                    raise PreflightStopped('读取掘金标签前身份变化')
                for tag in tags[:3]:
                    page.goto('https://juejin.cn/tag/' + quote(tag), wait_until='domcontentloaded', timeout=20000)
                    page.locator('a.title[href*="/post/"]').first.wait_for(timeout=8000)
                    latest = page.get_by_text('最新', exact=True)
                    if latest.count() == 1:
                        latest.click(timeout=5000)
                        page.wait_for_timeout(800)
                    for url in page.locator('a.title[href*="/post/"]').evaluate_all('(xs)=>xs.slice(0,6).map(x=>x.href)'):
                        url = juejin_thread_url(url)
                        if url not in links:
                            links.append(url)
                for url in links[:18]:
                    try:
                        page.goto(url, wait_until='domcontentloaded', timeout=15000)
                        meta = read_article(page)
                        if not set(tags).intersection(meta['tags']):
                            continue
                        if meta['author_id'] == account['identity'] or not 0 <= time.time() - meta['created'] <= 30 * 86400:
                            continue
                        if re.search(r'代充|返佣|加群|拼团|加微|招代理|破解版|购买链接', meta['excerpt']):
                            continue
                        result.append(meta)
                    except Exception:
                        continue
            finally:
                page.close()
            return result
