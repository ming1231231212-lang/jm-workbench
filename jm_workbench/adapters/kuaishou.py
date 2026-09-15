"""Use the user's dedicated Chrome; bounded visible navigation and one-shot sends."""
import json
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlparse

from ..policies.rules import ID_RE
from .errors import LocalBrowserError, PlatformRisk as Blocked
from .chrome import endpoint

CAMPAIGN = "jm"
EXTRACT = (Path(__file__).parent / "extract.js").read_text(encoding="utf-8")
RISK_TEXT = ("操作频繁", "访问过于频繁", "账号异常", "账号被封禁", "拖动滑块", "完成安全验证", "访问受限", "网络环境存在风险")


class Browser:
    def __init__(self, account):
        self.profile = account["profile_dir"]

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.pw = None
        try:
            ws_endpoint = endpoint(self.profile)
            self.pw = sync_playwright().start()
            self.browser = self.pw.chromium.connect_over_cdp(ws_endpoint, timeout=30000)
            self.page = next((p for c in self.browser.contexts for p in c.pages if urlparse(p.url).hostname == "www.kuaishou.com"), None)
            open_home = self.page is None
            if open_home:
                if not self.browser.contexts:
                    raise LocalBrowserError('专用 Chrome 没有可用窗口，请重新打开')
                self.page = self.browser.contexts[0].new_page()
        except Exception as ex:
            if self.pw:
                self.pw.stop()
            if isinstance(ex, LocalBrowserError):
                raise
            raise LocalBrowserError('本机 Chrome 连接未成功，请重新打开专用浏览器后重试；尚未读取快手页面') from ex
        try:
            self.page.set_default_timeout(10000)
            self.network_risk = ""
            self.page.on("response", self._response)
            if open_home:
                # User-authorized task session; open the missing target page normally.
                response = self.page.goto('https://www.kuaishou.com/', wait_until='domcontentloaded', timeout=25000)
                if response and response.status >= 400:
                    raise Blocked('页面 HTTP ' + str(response.status))
                self.page.wait_for_timeout(1200)
                self.check_page()
            return self
        except BaseException:
            self.pw.stop()
            raise

    def __exit__(self, *args):
        self.page.remove_listener("response", self._response)
        self.pw.stop()  # Disconnect the client; preserve Chrome and its profile.

    def _response(self, response):
        u = urlparse(response.url)
        if u.hostname == "www.kuaishou.com" and (u.path == "/graphql" or u.path.startswith("/rest/")) and response.status in (401, 403, 429):
            self.network_risk = "平台 HTTP " + str(response.status)

    def check_page(self):
        if self.network_risk:
            raise Blocked(self.network_risk)
        if urlparse(self.page.url).hostname != "www.kuaishou.com":
            raise Blocked("页面跳转到其他站点")
        text = self.page.locator("body").inner_text(timeout=8000)
        for word in RISK_TEXT:
            if word in text:
                raise Blocked("平台提示：" + word)
        if self.page.locator('iframe[src*="captcha"],iframe[src*="verify"]').count():
            raise Blocked("页面存在安全验证，请人工处理")

    def navigate(self, url):
        self.check_page()
        response = self.page.goto(url, wait_until="domcontentloaded", timeout=25000)
        if response and response.status >= 400:
            raise Blocked("页面 HTTP " + str(response.status))
        self.page.wait_for_timeout(1200)
        self.check_page()

    def extract(self, kind, value=""):
        self.check_page()
        expression = {
            "search": "extract.search(window.INIT_STATE,window.__APOLLO_STATE__,location.href,arg)",
            "detail": "extract.detail(window.__APOLLO_STATE__,location.href,arg)",
            "account": "extract.account(window.INIT_STATE,window.__APOLLO_STATE__)",
        }[kind]
        return self.page.evaluate("arg => {" + EXTRACT + "; return " + expression + ";}", value)

    def account(self):
        # Obtain current account from a fresh normal page, not a cached unrelated user's id.
        self.navigate("https://www.kuaishou.com/")
        try:
            return self.extract("account")
        except Exception as ex:
            if 'LOGIN_NOT_VERIFIED' in str(ex):
                raise LocalBrowserError('快手页面已打开，请先在专用 Chrome 登录，再点击检查并连接当前账号') from ex
            raise

    def search(self, keyword):
        if not keyword or len(keyword) > 40 or any(c in keyword for c in ".\r\n"):
            raise Blocked("关键词不正确")
        self.navigate("https://www.kuaishou.com/search/video?searchKey=" + quote(keyword))
        r = self.extract("search", keyword)
        return [{**row, "campaign": CAMPAIGN, "observed_at": time.time(), "detail_verified": False,
                 "source": {"kind": "search", "query": keyword, "url": self.page.url, "path": r["source_path"]}}
                for row in r["rows"]]

    def detail(self, vid):
        if not ID_RE.fullmatch(vid):
            raise Blocked("视频 ID 不正确")
        self.navigate("https://www.kuaishou.com/short-video/" + vid)
        self.page.evaluate("() => document.querySelectorAll('video').forEach(v => v.pause())")
        r = self.extract("detail", vid)
        return {**r, "campaign": CAMPAIGN, "observed_at": time.time(),
                "source": {"kind": "detail", "url": self.page.url, "path": r["source_path"]}}

    def send(self, expected, comment):
        """Called only after atomic reservation and final review check. Never retry."""
        self.check_page()
        current = self.extract("detail", expected["video_id"])
        if any(current[k] != expected[k] for k in ("video_id", "author_id", "caption", "nickname")) or current["can_comment"] is not True:
            return {"ok": False, "not_sent": True, "reason": "发布前视频、作者或评论权限变化"}
        box = self.page.locator('textarea[placeholder="说点什么..."]')
        if box.count() != 1 or not box.is_visible() or not box.is_enabled():
            return {"ok": False, "not_sent": True, "reason": "页面评论输入框不可用，未发送"}
        query = "mutation visionAddComment($photoId: String, $photoAuthorId: String, $content: String) { visionAddComment(photoId: $photoId, photoAuthorId: $photoAuthorId, content: $content) { result commentId status } }"
        body = {"operationName": "visionAddComment", "variables": {"photoId": expected["video_id"], "photoAuthorId": expected["author_id"], "content": comment}, "query": query}
        try:
            response = self.page.evaluate("""async body => {
                const r = await fetch('/graphql', {method:'POST',headers:{'Content-Type':'application/json'},
                  body:JSON.stringify(body),signal:AbortSignal.timeout(15000)});
                return {http:r.status,body:await r.json()};
            }""", body)
        except Exception as e:
            return {"ok": False, "uncertain": True, "reason": "请求结果不确定：" + type(e).__name__}
        return parse_receipt(response)


def parse_receipt(response):
    body = response.get("body") or {}
    data = (body.get("data") or {}).get("visionAddComment") or {}
    ok = response.get("http") == 200 and not body.get("errors") and data.get("result") == 1 and bool(data.get("commentId"))
    return {"ok": bool(ok), "uncertain": not ok, "code": str(data.get("result", response.get("http", "unknown"))),
            "comment_id": str(data.get("commentId") or ""),
            "reason": "平台返回评论ID，可见性尚未核验" if ok else "平台未确认成功，停发并人工核验"}
