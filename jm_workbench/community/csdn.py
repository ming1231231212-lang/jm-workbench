"""CSDN native browser publishing, exact content and one persisted attempt only."""
import json
import re
import time
from datetime import datetime
from urllib.parse import parse_qs, quote, urlparse

from .adapters import NotSubmitted, PreflightStopped
from .registry import csdn_thread_url, tag_label
from ..adapters.chrome import endpoint

ARTICLE_WRITE = '/blog-console-api/v3/mdeditor/saveArticle'
COMMENT_WRITE = '/phoenix/web/v1/comment/submit'
TITLE_PLACEHOLDER = '请输入文章标题（5~100个字）'
TAG_PLACEHOLDER = '请输入文字搜索，Enter键入可添加自定义标签'
SUMMARY_PLACEHOLDER = '本内容会在各展现列表中展示，帮助读者快速了解内容。若不填，则默认提取正文前256个字。'


def validate_payload(payload, target):
    body = payload['body']
    if not re.search(r'AI\s*辅助', body, re.I):
        raise ValueError('CSDN内容需标注AI辅助整理')
    if re.search(r'https?://|www\.|\.(?:com|cn|net|org)\b|加[微Vv]|私信|加群|返佣|代充|购买链接', body, re.I):
        raise ValueError('CSDN自动内容不得包含营销外链、联系方式或引流话术')
    if payload.get('kind') == 'reply':
        csdn_thread_url(target)
        if not 20 <= len(body) <= 1000:
            raise ValueError('CSDN评论需20–1000字')
    else:
        if target not in ('', '博客'):
            raise ValueError('CSDN当前发布到个人博客，暂不自动创建专栏')
        if not 5 <= len(payload['title']) <= 100 or not 200 <= len(body) <= 12000:
            raise ValueError('CSDN文章标题需5–100字，正文需200–12000字')
        if not 1 <= len(payload.get('platform_tags', [])) <= 3:
            raise ValueError('请为CSDN文章配置1–3个相关标签')
        for tag in payload['platform_tags']:
            tag_label(tag)


def identity(page):
    if urlparse(page.url).hostname not in ('www.csdn.net', 'blog.csdn.net'):
        raise PreflightStopped('CSDN身份页发生跳转，尚未提交')
    links = page.locator('#csdn-toolbar a.hasAvatar')
    try:
        links.first.wait_for(state='attached', timeout=10000)
        hrefs = links.evaluate_all('(es)=>es.map(e=>e.href)')
        ids = {m.group(1) for href in hrefs if (m := re.fullmatch(r'https://blog\.csdn\.net/([A-Za-z0-9_-]{2,100})/?', href))}
        if len(ids) == 1:
            return ids.pop()
    except Exception:
        pass
    raise PreflightStopped('CSDN账号未登录或身份不可核验，请在账号Chrome完成登录')


def safety_check(page):
    for selector in ('iframe[src*="captcha"]', 'iframe[src*="verify"]', '.geetest_panel', '.verify-bar', '.nc-container'):
        if page.locator(selector + ':visible').count():
            raise NotSubmitted('CSDN要求安全验证，已停止；请到网站处理')


def read_article(page):
    url = csdn_thread_url(page.url)
    page.locator('#content_views').wait_for(timeout=8000)
    title = page.locator('h1').inner_text().strip()
    body = page.locator('#content_views').inner_text().strip()
    author = urlparse(url).path.split('/')[1]
    native = page.evaluate('()=>({id:String(window.articleId||""),author:String(window.username||"")})')
    if native != {'id': url.rsplit('/', 1)[-1], 'author': author} or not title or len(body) < 20:
        raise PreflightStopped('CSDN原帖作者或正文无法核验')
    created = page.locator('meta[property="article:published_time"]').get_attribute('content')
    tags = page.locator('meta[name="keywords"]').get_attribute('content') or ''
    return {'url': url, 'title': title[:200], 'excerpt': body[:6000], 'author_id': author,
            'created': datetime.fromisoformat(created).timestamp(), 'tags': [t.strip() for t in tags.split(',') if t.strip()]}


def receipt(data, kind, target, expected):
    if not isinstance(data, dict) or 'code' not in data:
        raise RuntimeError('CSDN回执缺少明确结果码，禁止重发')
    if str(data['code']) != '200':
        raise NotSubmitted('CSDN拒绝提交：' + str(data.get('message') or data.get('msg') or '请到网站核实')[:180])
    inner = data.get('data')
    if kind == 'reply':
        ident = str(inner) if isinstance(inner, (str, int)) and not isinstance(inner, bool) else ''
        if isinstance(inner, dict):
            ident = str(inner.get('commentId') or inner.get('id') or '')
            if inner.get('articleId') and str(inner['articleId']) != target.rsplit('/', 1)[-1]:
                raise RuntimeError('CSDN评论回执目标不一致')
        url = csdn_thread_url(target)
    else:
        if not isinstance(inner, dict):
            raise RuntimeError('CSDN文章回执不可识别，禁止重发')
        ident = str(inner.get('id') or inner.get('article_id') or inner.get('articleId') or '')
        url = csdn_thread_url(inner.get('url') or inner.get('article_url') or f'https://blog.csdn.net/{expected}/article/details/{ident}')
        if urlparse(url).path.split('/')[1] != expected or url.rsplit('/', 1)[-1] != ident:
            raise RuntimeError('CSDN文章回执作者或编号不一致')
    if not re.fullmatch(r'[1-9][0-9]{3,23}', ident):
        raise RuntimeError('CSDN未返回明确内容编号，禁止重发')
    result = {'post_id': ident, 'url': url, 'visibility': 'unverified'}
    if kind == 'reply':
        result.update(comment_id=ident, thread_id=url.rsplit('/', 1)[-1])
    return result


def response_receipt(response, kind, target, expected):
    """Keep an actionable failure reason without recording headers or response data."""
    try:
        data = response.json()
    except Exception:
        data = None
    if response.status in (400, 401, 403, 422, 429):
        detail = (data.get('message') or data.get('msg')) if isinstance(data, dict) else None
        if not isinstance(detail, str) or '<' in detail:
            detail = '平台未返回可读原因，请到创作中心核实'
        detail = re.sub(r'https?://\S+', '[链接]', detail)
        detail = re.sub(r'(?i)(token|cookie|authorization|password)\s*[:=]\s*\S+', r'\1=[已隐藏]', detail)
        raise NotSubmitted(f'CSDN拒绝提交（HTTP {response.status}）：' + detail[:180])
    if not 200 <= response.status < 300:
        raise RuntimeError(f'CSDN提交结果不明（HTTP {response.status}），禁止重发')
    return receipt(data, kind, target, expected)


class SubmitGuard:
    def __init__(self, payload, target):
        self.payload, self.target = payload, target
        self.armed = False
        self.count = 0
        self.blocked = False

    def valid(self, data):
        if self.payload.get('kind') == 'reply':
            return (data.get('content') == self.payload['body'] and str(data.get('articleId')) == self.target.rsplit('/', 1)[-1]
                    and not data.get('commentId') and not data.get('replyId'))
        return (data.get('title') == self.payload['title'] and data.get('markdowncontent', '').strip() == self.payload['body'].strip()
                and data.get('tags', '').split(',') == self.payload['platform_tags'] and data.get('status') == 0
                and data.get('pubStatus') == 'publish' and data.get('readType') == 'public' and data.get('type') == 'original'
                and data.get('creation_statement') == 1 and data.get('sync_git_code') == 0
                and not data.get('id') and not data.get('articleId') and not data.get('categories')
                and not data.get('original_link') and not data.get('cover_images') and not data.get('creator_activity_id'))

    def route(self, route):
        req = route.request
        if req.method != 'POST':
            return route.abort('blockedbyclient')
        if not self.armed:
            # Preparing may trigger a private autosave on the same endpoint. No public write is permitted yet.
            return route.abort('blockedbyclient')
        self.count += 1
        try:
            if self.payload.get('kind') == 'reply':
                pairs = parse_qs(req.post_data or '', keep_blank_values=True)
                valid = all(len(v) == 1 for v in pairs.values()) and self.valid({k: v[0] for k, v in pairs.items()})
            else:
                valid = self.valid(json.loads(req.post_data or '{}'))
        except Exception:
            valid = False
        if self.count != 1 or not valid:
            self.blocked = True
            return route.abort('blockedbyclient')
        route.fallback()


def prepare_reply(page, payload, expected, target):
    meta = read_article(page)
    if meta['url'] != target or meta['author_id'] == expected:
        raise PreflightStopped('CSDN目标变化或为本人文章，未提交')
    if meta['title'] != payload.get('source_title') or not payload.get('source_excerpt') or not meta['excerpt'].startswith(payload['source_excerpt'].strip()):
        raise PreflightStopped('CSDN原帖快照不一致，未提交')
    safety_check(page)
    page.locator('#toolBarBox .go-side-comment').click(timeout=5000)
    editor = page.locator('#comment_content')
    editor.wait_for(timeout=8000)
    # CSDN restores its own unsent draft. Only reuse the exact authorized payload.
    if editor.input_value().strip() not in ('', payload['body']):
        raise PreflightStopped('评论框已有其他内容，已保留')
    if page.locator('#comment_replyId').input_value():
        raise PreflightStopped('评论框正在回复其他评论，未提交')
    editor.fill(payload['body'])
    if editor.input_value() != payload['body'] or identity(page) != expected:
        raise PreflightStopped('CSDN评论或账号发生变化，未提交')
    safety_check(page)
    return page.locator('input.btn-comment-input')


def prepare_article(page, payload):
    page.locator('#import-markdown-file-input').wait_for(state='attached', timeout=10000)
    modal = page.locator('.modal:visible')
    if modal.count() == 1 and '模版库' in modal.inner_text():
        modal.locator('.modal__close-button:visible').click(timeout=5000)
    title = page.get_by_placeholder(TITLE_PLACEHOLDER)
    editor = page.locator('pre.editor__inner[contenteditable=true]')
    old = editor.text_content().strip()
    welcome = title.input_value() == '【无标题】' and old.startswith('@[TOC](这里写自定义目录标题)') and '# 欢迎使用Markdown编辑器' in old
    if not welcome and (old not in ('', payload['body']) or title.input_value() not in ('', '【无标题】', 'JM-article', payload['title'])):
        raise PreflightStopped('CSDN编辑器已有其他草稿，已保留')
    # Native import preserves Markdown newlines; contenteditable.fill loses them.
    page.locator('#import-markdown-file-input').set_input_files({'name': payload['title'] + '.md', 'mimeType': 'text/markdown', 'buffer': payload['body'].encode()})
    page.wait_for_function('(body)=>document.querySelector("pre.editor__inner")?.textContent.trim()===body', arg=payload['body'].strip(), timeout=5000)
    if not title.is_visible():
        try:
            page.locator('.article-bar__title-display').click(timeout=2000)
        except Exception:
            # The first-use template picker can arrive asynchronously after import.
            picker = page.locator('.modal:visible')
            if picker.count() != 1 or '模版库' not in picker.inner_text():
                raise PreflightStopped('CSDN标题被其他窗口遮挡，未提交') from None
            picker.locator('.modal__close-button:visible').click(timeout=5000)
            page.locator('.article-bar__title-display').click(timeout=5000)
    title.fill(payload['title'])
    if editor.text_content().strip() != payload['body'].strip():
        raise PreflightStopped('CSDN导入正文与快照不一致')
    page.get_by_role('button', name='发布文章', exact=True).click(timeout=5000)
    page.get_by_role('button', name='添加文章标签').wait_for(timeout=10000)
    modal = page.locator('.modal:visible')
    existing = [s.strip() for s in modal.locator('.mark_selection_box_el_tag').all_text_contents()]
    if existing and existing != payload['platform_tags']:
        raise PreflightStopped('CSDN编辑器已有不同标签，未提交')
    if not existing:
        page.get_by_role('button', name='添加文章标签').click(timeout=5000)
        for tag in payload['platform_tags']:
            page.get_by_placeholder(TAG_PLACEHOLDER).fill(tag)
            page.get_by_role('option', name=tag, exact=True).click(timeout=7000)
    modal.get_by_text('文章摘要', exact=True).click(timeout=5000)
    page.get_by_placeholder(SUMMARY_PLACEHOLDER).fill(re.sub(r'[#\n]+', ' ', payload['body'])[:180])
    page.get_by_placeholder('无声明', exact=True).click(timeout=5000)
    page.locator('.el-select-dropdown:visible').get_by_text('部分内容由AI辅助生成', exact=True).click(timeout=5000)
    backup = modal.locator('label').filter(has_text='同时备份到GitCode').locator('input')
    if backup.is_checked():
        modal.locator('label').filter(has_text='同时备份到GitCode').click(timeout=5000)
    if backup.is_checked() or not modal.locator('#public').is_checked() or not modal.locator('#multiPlatformPublishNo').is_checked():
        raise PreflightStopped('CSDN可见性或额外同步选项不符合任务')
    if title.input_value() != payload['title'] or editor.text_content().strip() != payload['body'].strip():
        raise PreflightStopped('CSDN提交前文章快照不一致')
    safety_check(page)
    return modal.get_by_role('button', name='发布文章', exact=True)


class CsdnBrowser:
    def run(self, account, payload, target):
        from playwright.sync_api import sync_playwright
        if payload:
            validate_payload(payload, target)
        try:
            ws = endpoint(account['profile_dir'])
        except Exception:
            raise PreflightStopped('CSDN账号浏览器未连接，请先登录 / 打开') from None
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.connect_over_cdp(ws, timeout=10000)
            except Exception:
                raise PreflightStopped('CSDN账号Chrome连接未完成') from None
            context = browser.contexts[0]
            home = context.new_page()
            page = None
            try:
                home.goto('https://www.csdn.net/', wait_until='domcontentloaded', timeout=20000)
                actual = identity(home)
                if payload is None:
                    return actual
                if actual != account['identity']:
                    raise PreflightStopped('CSDN登录身份变化，未提交')
                kind = payload.get('kind', 'thread')
                host, path = ('blog.csdn.net', COMMENT_WRITE) if kind == 'reply' else ('bizapi.csdn.net', ARTICLE_WRITE)
                page = context.new_page()
                guard = SubmitGuard(payload, target)
                page.route('**' + path + '*', guard.route)
                try:
                    page.goto(target if kind == 'reply' else 'https://editor.csdn.net/md/', wait_until='domcontentloaded', timeout=20000)
                    button = prepare_reply(page, payload, actual, target) if kind == 'reply' else prepare_article(page, payload)
                    if kind != 'reply':
                        home.reload(wait_until='domcontentloaded', timeout=20000)
                        if identity(home) != actual:
                            raise PreflightStopped('CSDN发文前账号变化，未提交')
                    if not button.is_enabled():
                        raise PreflightStopped('CSDN提交按钮不可用，未提交')
                except (NotSubmitted, PreflightStopped):
                    raise
                except Exception:
                    raise PreflightStopped('CSDN编辑器或标签核验未完成，尚未提交') from None
                guard.armed = True
                # Any error after the one click is uncertain; service stops without automatic retry.
                with page.expect_response(lambda r: urlparse(r.url).hostname == host and urlparse(r.url).path == path and r.request.method == 'POST', timeout=25000) as waiting:
                    button.click(timeout=5000)
                response = waiting.value
                if guard.count != 1 or guard.blocked:
                    raise RuntimeError('CSDN请求核对失败，禁止重发')
                return response_receipt(response, kind, target, actual)
            finally:
                if page is not None:
                    page.close()
                home.close()

    def discover(self, account, keywords):
        # Until bounded native search is verified, explicit original-post materials are supported.
        raise PreflightStopped('CSDN自动查找目标尚未验收，请补充已核对原文的指定帖评论素材')
