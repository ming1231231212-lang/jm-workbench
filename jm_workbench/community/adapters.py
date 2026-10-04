"""One attempt only. API errors after an ambiguous response never trigger retries."""
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
from ..adapters.chrome import endpoint
from ..adapters.errors import LocalBrowserError
from .registry import platform, compose_url, safe_post_url, destination, tieba_thread_url


class NotSubmitted(ValueError):
    """Definitively no write, e.g. failed preflight or explicit API rejection."""


class PreflightStopped(NotSubmitted):
    """Local read-only preparation stopped before the submission helper was called."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def http_json(method, url, headers, data=None, form=False):
    payload=None if data is None else (urlencode(data).encode() if form else json.dumps(data).encode())
    headers={'User-Agent':'JMWorkbench/1.0 (local authorized community publisher)', **headers}
    if data is not None:
        headers['Content-Type']='application/x-www-form-urlencoded' if form else 'application/json'
    req=urllib.request.Request(url,data=payload,headers=headers,method=method)
    # No redirect of an Authorization header or POST, no retry transport.
    try:
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=25) as response:
            return json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as ex:
        if 400<=ex.code<500:
            message={401:'登录授权已过期',403:'账号没有发布权限或平台限制',429:'平台限流，已停止本平台任务'}.get(ex.code,'平台拒绝请求，请检查内容和板块')
            raise NotSubmitted(message) from None
        raise RuntimeError('请求结果不明，请到平台核实，工作台不会重发') from None


def tieba_identity(page):
    if urlparse(page.url).hostname!='tieba.baidu.com':
        raise NotSubmitted('请在账号浏览器打开百度贴吧，完成登录后会自动同步')
    data=page.evaluate('''() => {
      const root=[...document.querySelectorAll('.pc-main-page-layout, .top-bar-wrapper')].find(e=>e.__vue__?.$pinia);
      const state=root?.__vue__.$pinia.state.value.userStore;
      const u=state ? (state.user || {}) : (window.PageData?.user || {});
      const flag=state ? state.isLogin : (u.is_login ?? u.isLogin);
      return {authenticated:flag===true || flag===1 || flag==='1', id:String(u.user_id||u.id||'').trim()};
    }''')
    if not data.get('authenticated') or not data.get('id') or data['id']=='0':
        raise NotSubmitted('等待贴吧登录，请在账号浏览器完成登录；页面加载完成后会自动同步')
    # Nickname can be empty or changed. Only the stable platform ID is an identity.
    return data['id']


def tieba_existing_identity(context):
    """Inspect only this account's already-open pages; never navigate or create tabs."""
    pages=[p for p in context.pages if urlparse(p.url).hostname=='tieba.baidu.com']
    if not pages:raise NotSubmitted('浏览器已连接，请在该账号窗口打开百度贴吧并登录')
    identities=set();message='贴吧页面正在加载，稍后会自动同步'
    for page in pages:
        try:identities.add(tieba_identity(page))
        except NotSubmitted as ex:message=str(ex)
        except Exception:continue # A tab can navigate/close while being inspected.
    if len(identities)>1:raise NotSubmitted('多个贴吧页面的身份不一致，请刷新账号页面后重新检查')
    if identities:return identities.pop()
    raise NotSubmitted(message)


def tieba_wait_identity(page,expected,timeout=10000):
    """The Vue root can precede the asynchronous userStore login response."""
    deadline=time.monotonic()+timeout/1000
    while True:
        try:actual=tieba_identity(page)
        except NotSubmitted:
            if time.monotonic()>=deadline:raise PreflightStopped('新页面登录状态未就绪，尚未填写或提交；请检查账号页面') from None
            page.wait_for_timeout(200);continue
        if actual!=expected:raise PreflightStopped('新页面登录身份不一致，未提交')
        return actual


def tieba_receipt(data):
    inner=data.get('data') if isinstance(data.get('data'),dict) else {}
    codes=[data.get('error_code'),data.get('errno'),inner.get('error_code')]
    if any(c is not None and str(c)!='0' for c in codes):
        raise NotSubmitted('贴吧拒绝发布或要求安全验证，已停止；请到网站处理')
    ident=inner.get('tid') or inner.get('thread_id') or data.get('tid') or data.get('thread_id')
    if not ident or not re.fullmatch(r'[0-9]+',str(ident)):
        raise RuntimeError('贴吧未返回明确帖子编号，结果不明')
    return {'post_id':str(ident),'url':'https://tieba.baidu.com/p/'+str(ident),'visibility':'unverified'}


def tieba_editor_text(editor):
    # Chrome innerText adds CSS paragraph spacing; Quill serializes one newline
    # per block. Preserve real blank paragraphs, never ignore words or punctuation.
    return editor.evaluate(r'''e=>{
      const blocks=Array.from(e.children);
      return blocks.length && blocks.every(n=>n.tagName==='P')
        ? blocks.map(n=>n.innerText.replace(/[\r\n]+$/,'')).join('\n') : e.innerText;
    }''').strip()


def tieba_fill_and_submit(page, payload, expected, target):
    """Only the exact visible editor is supported; no guessed clicks or retries."""
    if urlparse(page.url).hostname!='tieba.baidu.com':
        raise NotSubmitted('贴吧页面发生跳转，请先完成登录或验证')
    if tieba_identity(page)!=expected:
        raise NotSubmitted('贴吧当前身份已变化，已停止发送')
    for selector in ('iframe[src*="captcha"]','iframe[src*="verify"]','.geetest_panel','.vcode-dialog'):
        if page.locator(selector).count() and page.locator(selector).first.is_visible():
            raise NotSubmitted('贴吧要求安全验证，请在网站完成，任务已停止')
    # Current PC editor (observed 2026-10-03): two Quill editors in a publisher dialog.
    if page.locator('#tb-editor-title').count()==0:
        launch=page.locator('.forum-operate .operate-btn.publish:visible')
        if launch.count()!=1:raise NotSubmitted('没有找到当前吧的发贴入口，未提交')
        launch.click(timeout=5000)
    title=page.locator('#tb-editor-title .ql-editor[contenteditable="true"]:visible')
    body=page.locator('#tb-editor-content .ql-editor[contenteditable="true"]:visible')
    try:title.wait_for(state='visible',timeout=10000)
    except Exception:raise NotSubmitted('发贴编辑器未打开，请检查登录和板块权限') from None
    submit=page.locator('.footer-safe-issue .issue-btn:visible')
    if title.count()!=1 or body.count()!=1 or submit.count()!=1:
        raise NotSubmitted('贴吧编辑器不可用或已变化，未点击发布')
    selected=page.evaluate('''()=>{const root=document.querySelector('.pc-main-page-layout');const s=root?.__vue__?.$pinia?.state.value.publishStore?.selectedForum;return s?.name||s?.forum_name||'';}''')
    if selected!=target:raise NotSubmitted('编辑器所选贴吧与任务不一致，未提交')
    if title.inner_text().strip() or body.inner_text().strip():
        raise NotSubmitted('贴吧编辑器已有未保存内容，已保留；请在网站处理后继续')
    title.fill(payload['title'])
    body.fill(payload['body'])
    if tieba_editor_text(title)!=payload['title'] or tieba_editor_text(body)!=payload['body'].strip():
        raise PreflightStopped('编辑器内容核对未通过，未点击发布')
    if tieba_identity(page)!=expected:
        raise NotSubmitted('发布前身份变化，未点击发布')
    # From this line onward any failure is uncertain. Never click a second time.
    count=[0]
    def once(route):
        if route.request.method!='POST':return route.fallback()
        count[0]+=1
        if count[0]>1:return route.abort('blockedbyclient')
        route.fallback()
    page.route('**/c/c/thread/add_pc*',once)
    with page.expect_response(lambda r:urlparse(r.url).hostname=='tieba.baidu.com' and urlparse(r.url).path=='/c/c/thread/add_pc' and r.request.method=='POST',timeout=25000) as waiting:
        submit.click(timeout=10000)
    response=waiting.value
    if response.status in (400,401,403,422,429):raise NotSubmitted('贴吧拒绝请求，已暂停本平台')
    if not response.ok:raise RuntimeError('贴吧请求结果不明')
    return tieba_receipt(response.json())


def tieba_reply_receipt(data,target):
    inner=data.get('data') if isinstance(data.get('data'),dict) else {}
    if any(c is not None and str(c)!='0' for c in (data.get('errno'),data.get('error_code'),inner.get('error_code'))):
        raise NotSubmitted('贴吧拒绝评论或要求安全验证，已停止；请到网站处理')
    post=inner.get('post') or data.get('post') or {}
    ident=inner.get('pid') or data.get('pid') or post.get('id')
    if not ident or not re.fullmatch(r'[1-9][0-9]*',str(ident)):
        raise RuntimeError('贴吧未返回明确评论编号，结果不明')
    url=tieba_thread_url(target)
    return {'post_id':str(ident),'comment_id':str(ident),'thread_id':url.rsplit('/',1)[-1],
            'url':url+'?pid='+str(ident)+'#'+str(ident),'visibility':'unverified'}


def tieba_reply_and_submit(page,payload,expected,target):
    target=tieba_thread_url(target)
    if tieba_thread_url(page.url)!=target or tieba_identity(page)!=expected:
        raise NotSubmitted('评论目标或贴吧身份发生变化，未提交')
    if payload.get('source_title'):
        try:actual=page.locator('.pb-title').first.inner_text(timeout=5000).strip()
        except Exception:raise NotSubmitted('原帖标题无法核验，未提交') from None
        if actual!=payload['source_title']:raise NotSubmitted('原帖内容发生变化，未提交')
        if payload.get('source_excerpt'):
            actual_body=page.locator('.pb-content-wrap').first.inner_text(timeout=5000).strip()
            if not actual_body.startswith(payload['source_excerpt'].strip()):raise NotSubmitted('原帖正文发生变化，未提交')
    for selector in ('iframe[src*="captcha"]','iframe[src*="verify"]','.geetest_panel','.vcode-dialog'):
        if page.locator(selector).count() and page.locator(selector).first.is_visible():
            raise NotSubmitted('贴吧要求安全验证，评论已停止')
    box=page.locator('.pc-pb-reply-box')
    editor=box.locator('#tb-editor-pb-content .ql-editor[contenteditable="true"]:visible')
    if not editor.count():
        launcher=box.locator('.box:visible')
        if launcher.count()!=1:raise NotSubmitted('此帖回复入口不可用，未提交')
        launcher.click(timeout=5000)
    try:editor.wait_for(state='visible',timeout=8000)
    except Exception:raise NotSubmitted('此帖无法打开回复编辑器，未提交') from None
    submit=box.locator('.publish-btn:visible')
    if editor.count()!=1 or submit.count()!=1:raise NotSubmitted('回复编辑器发生变化，未提交')
    if editor.inner_text().strip():raise NotSubmitted('回复编辑器已有内容，已保留，未提交')
    editor.fill(payload['body'])
    if tieba_editor_text(editor)!=payload['body'].strip():raise PreflightStopped('评论正文核对失败，未提交')
    if tieba_identity(page)!=expected or tieba_thread_url(page.url)!=target:
        raise NotSubmitted('提交前账号或目标变化，未提交')
    count=[0];blocked=[False]
    def once(route):
        if route.request.method!='POST':return route.fallback()
        count[0]+=1
        try:
            raw=route.request.post_data or ''
            data=json.loads(raw) if raw.lstrip().startswith('{') else {k:v[0] for k,v in parse_qs(raw).items()}
            valid=str(data.get('tid',''))==target.rsplit('/',1)[-1] and not any(data.get(k) for k in ('quote_id','repostid','sub_post_id'))
        except Exception:valid=False
        if count[0]>1:return route.abort('blockedbyclient')
        if not valid:
            blocked[0]=True;return route.abort('blockedbyclient')
        route.fallback()
    page.route('**/c/c/post/add_pc*',once)
    with page.expect_response(lambda r:urlparse(r.url).hostname=='tieba.baidu.com' and urlparse(r.url).path=='/c/c/post/add_pc' and r.request.method=='POST',timeout=25000) as waiting:
        submit.click(timeout=10000)
    response=waiting.value
    if response.status in (400,401,403,422,429):raise NotSubmitted('贴吧拒绝评论请求，已暂停本平台')
    if not response.ok or blocked[0]:raise RuntimeError('贴吧评论结果不明')
    return tieba_reply_receipt(response.json(),target)


class CommunityAdapter:
    def __init__(self, config, transport=http_json):
        self.config,self.transport=config,transport

    def headers(self, account, secret):
        if not secret:raise NotSubmitted('尚未配置API密钥，请到社区账号填写')
        if '\n' in secret or '\r' in secret:raise NotSubmitted('API密钥格式无效')
        return {'api-key':secret} if account['platform']=='dev' else {'Authorization':'Bearer '+secret}

    def check(self, account, secret):
        p=account['platform']
        if p=='csdn':
            from .csdn import CsdnBrowser
            return CsdnBrowser().run(account,None,'')
        if p=='juejin':
            from .juejin import JuejinBrowser
            return JuejinBrowser().run(account,None,'')
        if p=='tieba':
            return self.tieba(account, None, '')
        if not platform(p)['automatic']:raise NotSubmitted('此平台使用网页发布，不提供自动身份核验')
        url={'dev':'https://dev.to/api/users/me','x':'https://api.x.com/2/users/me',
             'reddit':'https://oauth.reddit.com/api/v1/me','huggingface':'https://huggingface.co/api/whoami-v2'}[p]
        data=self.transport('GET',url,self.headers(account,secret))
        if p=='x':identity=str(data.get('data',{}).get('id',''))
        elif p=='dev':identity=str(data.get('id',''))
        else:identity=str(data.get('id') or data.get('name') or '')
        if not identity:raise NotSubmitted('平台未返回可核验的账号身份')
        return identity

    def discover(self,account,boards):
        """Read a bounded set of recent public threads; never click interaction buttons."""
        if account['platform']=='csdn':
            from .csdn import CsdnBrowser
            return CsdnBrowser().discover(account,boards)
        if account['platform']=='juejin':
            from .juejin import JuejinBrowser
            return JuejinBrowser().discover(account,boards)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser=pw.chromium.connect_over_cdp(endpoint(account['profile_dir']),timeout=10000)
            context=browser.contexts[0]
            if tieba_existing_identity(context)!=account['identity']:raise NotSubmitted('候选读取前身份变化')
            page=context.new_page();links=[];result=[]
            try:
                for board in boards:
                    page.goto(compose_url('tieba',board),wait_until='domcontentloaded',timeout=15000)
                    page.locator('.pc-main-page-layout').wait_for(timeout=8000)
                    for _ in range(2):
                        page.mouse.wheel(0,850);page.wait_for_timeout(500)
                        for value in page.locator('a[href*="/p/"]').evaluate_all('(xs)=>xs.filter(x=>x.innerText.length>12).map(x=>x.href)'):
                            try:url=tieba_thread_url(value)
                            except ValueError:continue
                            if url not in links:links.append(url)
                        if len(links)>=18:break
                for url in links[:18]:
                    try:
                        page.goto(url,wait_until='domcontentloaded',timeout=15000)
                        page.locator('.pb-title').first.wait_for(timeout=5000)
                        meta=page.evaluate('''()=>{const t=document.querySelector('.pc-main-page-layout')?.__vue__?.$pinia?.state.value.pbStore?.thread;
                          return {id:String(t?.id||''),author_id:String(t?.author?.id||''),created:Number(t?.create_time||0)};}''')
                        if meta['id']!=url.rsplit('/',1)[-1] or not meta['author_id'] or meta['author_id']==account['identity']:continue
                        if not 0<=time.time()-meta['created']<=30*86400:continue
                        title=page.locator('.pb-title').first.inner_text().strip()
                        excerpt=page.locator('.pb-content-wrap').first.inner_text().strip()[:6000]
                        if not title or not excerpt:continue
                        result.append({'url':url,'title':title[:200],'excerpt':excerpt,**meta})
                    except Exception:continue
            finally:page.close()
            return result

    def publish(self, account, secret, payload, target):
        p=account['platform']
        if p=='csdn':
            from .csdn import CsdnBrowser
            return CsdnBrowser().run(account,payload,target)
        if p=='juejin':
            from .juejin import JuejinBrowser
            return JuejinBrowser().run(account,payload,target)
        if payload.get('kind')=='reply':
            if p!='tieba':raise NotSubmitted('该平台尚未适配评论发布')
            target=tieba_thread_url(target)
        else:destination(p,target)
        if p=='tieba':return self.tieba(account,payload,target)
        if p not in ('dev','x','reddit','huggingface'):raise NotSubmitted('此平台尚未实现自动提交，请使用网页发布')
        headers=self.headers(account,secret)
        if p=='dev':
            # Frontmatter takes precedence on Forem. Disallow it to preserve snapshot semantics.
            if payload['body'].lstrip().startswith('---'):raise NotSubmitted('DEV正文不能以YAML配置头开头，请直接填写文章正文')
            data=self.transport('POST','https://dev.to/api/articles',headers,{'article':{'title':payload['title'],'body_markdown':payload['body'],'published':True,'tags':payload.get('tags',[])}})
            ident=data.get('id');url=data.get('url')
        elif p=='x':
            text=payload['title']+'\n\n'+payload['body']
            if len(text)>280:raise NotSubmitted('X文本超出本版本280字符限制，请缩短标题与正文')
            data=self.transport('POST','https://api.x.com/2/tweets',headers,{'text':text})
            ident=data.get('data',{}).get('id');url='https://x.com/i/status/'+str(ident)
        elif p=='reddit':
            data=self.transport('POST','https://oauth.reddit.com/api/submit',headers,{'api_type':'json','kind':'self','sr':target,'title':payload['title'],'text':payload['body'],'resubmit':'false'},form=True)
            result=data.get('json',{})
            if result.get('errors'):raise NotSubmitted('Reddit拒绝发帖，请检查社区权限、内容要求和限流状态')
            ident=result.get('data',{}).get('id');url=result.get('data',{}).get('url')
        else:
            bits=target.split('/')
            kind=bits[0] if len(bits)==3 else 'models'
            repo='/'.join(bits[-2:])
            data=self.transport('POST',f'https://huggingface.co/api/{kind}/{repo}/discussions',headers,{'title':payload['title'],'description':payload['body'],'pullRequest':False})
            ident=data.get('num');prefix='' if kind=='models' else kind+'/'
            url=f'https://huggingface.co/{prefix}{repo}/discussions/{ident}'
        if not ident or not url:raise RuntimeError('平台未返回帖子编号，结果不明，请勿重发')
        return {'post_id':str(ident),'url':safe_post_url(p,url),'visibility':'unverified'}

    def open(self, account, url):
        p=Path(account['profile_dir']).resolve()
        p.mkdir(parents=True,exist_ok=True)
        chrome=Path(self.config.values['chrome_path'])
        if not chrome.is_file():raise ValueError('未找到Chrome，请检查工作台设置')
        safe_post_url(account['platform'],url)
        # A visible window is intentional: the user pressed 登录/打开网页.
        subprocess.Popen([str(chrome),f'--user-data-dir={p}','--remote-debugging-port=0','--no-first-run','--no-default-browser-check',url],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        return {'message':'已打开此账号的独立Chrome，请完成登录'}

    def tieba(self, account, payload, target):
        from playwright.sync_api import sync_playwright
        try:ws=endpoint(account['profile_dir'])
        except LocalBrowserError:raise NotSubmitted('账号浏览器未连接，请先点击“登录 / 打开”') from None
        with sync_playwright() as pw:
            try:browser=pw.chromium.connect_over_cdp(ws,timeout=10000)
            except Exception:raise NotSubmitted('账号浏览器连接超时，请检查该账号Chrome是否仍在运行') from None
            if not browser.contexts:raise NotSubmitted('账号浏览器尚未就绪，请稍后检查')
            context=browser.contexts[0]
            if payload is None:return tieba_existing_identity(context)
            page=context.new_page()
            try:
                try:
                    page.goto(compose_url('tieba',target),wait_until='domcontentloaded',timeout=20000)
                    page.locator('.pc-main-page-layout').wait_for(state='visible',timeout=10000)
                    tieba_wait_identity(page,account['identity'])
                except PreflightStopped:raise
                except Exception:raise PreflightStopped('账号页面加载未完成，尚未调用发布操作') from None
                if payload.get('kind')=='reply':
                    return tieba_reply_and_submit(page,payload,account['identity'],target)
                return tieba_fill_and_submit(page,payload,account['identity'],target)
            finally:
                # This page was created by this attempt. Close to prevent the site's
                # own captcha retry loop from submitting after an uncertain outcome.
                page.close()
