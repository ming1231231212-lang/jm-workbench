"""Explicit native desktop publishing contract. No CDP, cookies or browser extension.

The caller owns reservation, budget and one-attempt journaling. This module never
retries a submit and does not enable schedules or change platform capabilities.
"""
import re
import time
from urllib.parse import urlsplit, parse_qs

from .zhihu import comment_target_url


class NativeStopped(ValueError):
    """Preflight proved that no submit was attempted."""


class NativeUnknown(RuntimeError):
    """The single submit may have happened; verification only, never resend."""


def normalized(value):
    return re.sub(r'[\s\u200b\ufeff\ufffc]', '', value or '')


def _path(value):
    u = urlsplit(value)
    return u.scheme + '://' + u.netloc + u.path.rstrip('/')


def profile_key(value):
    u = urlsplit(value)
    if u.hostname=='juejin.cn':
        match=re.fullmatch(r'/user/([1-9][0-9]{5,23})(?:/(?:posts|followers))?/?',u.path)
        if match:return 'juejin:'+match[1]
    if u.hostname == 'tieba.baidu.com' and u.path == '/home/main':
        ids = parse_qs(u.query).get('id', [])
        return 'tieba:' + ids[0] if len(ids) == 1 else ''
    return _path(value)


class NativePublisher:
    def __init__(self, ui, sleep=time.sleep, poll_attempts=12, before_submit=lambda: None, identity_ui=None):
        self.ui, self.sleep, self.poll_attempts = ui, sleep, poll_attempts
        self.before_submit = before_submit
        self.identity_ui=identity_ui

    def _snapshot(self, url):
        s = self.ui.call('snapshot')
        if _path(s.get('url', '')) != _path(url):
            raise NativeStopped('目标标签页已变化，未继续提交')
        return s

    def _wait_page(self, url, aliases=()):
        for _ in range(self.poll_attempts):
            s = self.ui.call('snapshot')
            if _path(s.get('url', '')) in {_path(url), *(_path(u) for u in aliases)} and s.get('text'):
                return s
            self.sleep(.5)
        raise NativeStopped('原页面尚未加载或需要本人登录验证，未提交')

    @staticmethod
    def _nodes(s, type=None, name=None):
        return [n for n in s.get('nodes', []) if n.get('visible')
                and (type is None or n.get('type') == type)
                and (name is None or normalized(n.get('name', '')) == normalized(name))]

    def _one(self, s, type, name=None):
        nodes = self._nodes(s, type, name)
        if len(nodes) != 1:
            raise NativeStopped('目标控件不唯一或不可见，未继续提交')
        return nodes[0]

    def _click(self, node, url):
        self._snapshot(url)
        self.ui.call('click', key=node['key'], expected_url=url)

    def check(self, account, binding):
        if self.identity_ui is not None:
            return NativePublisher(self.identity_ui,sleep=self.sleep,poll_attempts=self.poll_attempts).check(account,binding)
        p = account.get('platform')
        if p not in ('zhihu', 'tieba', 'juejin') or not account.get('enabled'):
            raise NativeStopped('此账号未启用本机身份检查')
        identity, profile = binding.get('identity'), binding.get('profile_url', '')
        u = urlsplit(profile)
        valid = (u.hostname == 'www.zhihu.com' and re.fullmatch(r'/people/[A-Za-z0-9_-]+', u.path) and not u.query) if p == 'zhihu' else (u.hostname == 'juejin.cn' and u.path == '/user/' + str(identity) and not u.query) if p == 'juejin' else (u.hostname == 'tieba.baidu.com' and u.path == '/home/main' and bool(parse_qs(u.query).get('id')))
        if not identity or u.scheme != 'https' or not valid or u.fragment or u.username or u.port:
            raise NativeStopped('本人主页绑定无效，未继续')
        if account.get('identity') and account['identity'] != identity:
            raise NativeStopped('账号身份已变化，不能自动换账号')
        self.ui.call('open', url=profile)
        s = self._wait_page(profile)
        marker = bool(self._nodes(s, 'Button', '编辑个人资料')) if p == 'zhihu' else bool(self._nodes(s, 'Button', '设置')) if p == 'juejin' else any(parse_qs(urlsplit(n.get('value', '')).query).get('id') == parse_qs(u.query).get('id') for n in self._nodes(s, 'Hyperlink', '我的'))
        if not marker or normalized(binding['name']) not in normalized(s['text']):
            raise NativeStopped('本人账号未登录或身份无法核验，未提交')
        if p == 'zhihu':
            for alias in binding.get('profile_aliases', []):
                u = urlsplit(alias)
                if u.scheme != 'https' or u.hostname != 'www.zhihu.com' or not re.fullmatch(r'/people/[A-Za-z0-9_-]+', u.path) or u.username or u.port or u.query or u.fragment:
                    raise NativeStopped('账号主页别名无效，未提交')
                self.ui.call('open', url=alias, allowed_redirects=[profile])
                s = self._wait_page(alias, [profile])
                if not self._nodes(s, 'Button', '编辑个人资料') or normalized(binding['name']) not in normalized(s['text']):
                    raise NativeStopped('主页别名不属于当前登录账号，未提交')
        return identity

    def publish(self, account, binding, payload, target):
        self.check(account, binding)
        if payload.get('kind') != 'reply':
            from .native_articles import prepare_article, verify_article
            ready = prepare_article(self, account, binding, payload, target)
            self.before_submit()
            try:
                self._click(ready['submit'], ready['url'])
                receipt=verify_article(self, account, binding, payload)
                if hasattr(self.ui,'clear_draft'):self.ui.clear_draft()
                return receipt
            except Exception as exc:
                raise NativeUnknown('文章已进入单次提交边界，结果不明；禁止自动重发') from exc
        if account.get('platform') != 'zhihu':
            from .native_replies import prepare_reply,verify_reply
            ready=prepare_reply(self,account,binding,payload,target)
            self.before_submit()
            try:
                self._click(ready['submit'],ready['url'])
                return verify_reply(self,account,binding,payload,ready)
            except Exception as exc:
                raise NativeUnknown('评论已进入单次提交边界，结果不明；禁止自动重发') from exc
        target = comment_target_url(target)
        body = payload.get('body', '').strip()
        if len(body) < 20 or len(body) > 2000 or not payload.get('source_title'):
            raise NativeStopped('评论正文或原文依据不完整，未提交')
        self.ui.call('open', url=target)
        s = self._wait_page(target)
        original = normalized(s['text'])
        title = normalized(payload['source_title'])
        anchors = [normalized(line) for line in payload.get('source_excerpt', '').splitlines()
                   if len(normalized(line)) >= 20 and normalized(line)!=title]
        if title not in original or not anchors or not any(a in original for a in anchors):
            raise NativeStopped('原帖标题或具体正文不一致，未提交')
        if not self._nodes(s, 'Button', '点击打开' + binding['name'] + '的主页'):
            raise NativeStopped('原帖当前登录账号无法核验，未提交')
        if any(normalized(n.get('name')) == normalized(body) for n in self._nodes(s, 'Text')):
            raise NativeStopped('原帖已出现相同评论，禁止再次提交')
        comments = [n for n in self._nodes(s, 'Button')
                    if re.fullmatch(r'(?:\d+条评论|添加评论)', normalized(n.get('name')))]
        if len(comments) != 1:
            raise NativeStopped('评论入口不明确，未提交')
        self._click(comments[0], target)
        self.sleep(.4)
        s = self._snapshot(target)
        editor = self._one(s, 'Edit', '')
        if normalized(editor.get('value')):
            raise NativeStopped('评论框存在未提交内容，未覆盖')
        self.ui.call('paste', key=editor['key'], expected_url=target, text=body)
        s = self._snapshot(target)
        editor = self._one(s, 'Edit', '')
        if normalized(editor.get('value')) != normalized(body):
            raise NativeStopped('评论全文回读不一致，未提交')
        send = self._one(s, 'Button', '发布')
        if not send.get('enabled', False):
            raise NativeStopped('平台发布按钮不可用，未提交')
        self.before_submit()
        # Never repeat this action, even when the click itself times out.
        try:
            self._click(send, target)
        except Exception as exc:
            raise NativeUnknown('已进入单次提交边界，结果不明；只允许核验，禁止重发') from exc
        for _ in range(self.poll_attempts):
            self.sleep(1)
            try:
                s = self._snapshot(target)
                nodes = s.get('nodes', [])
                found = [i for i, n in enumerate(nodes)
                         if n.get('type') == 'Text' and normalized(n.get('name')) == normalized(body)]
                empty = not normalized(self._one(s, 'Edit', '').get('value'))
                if len(found) == 1 and empty:
                    around = nodes[max(0, found[0] - 12):found[0]]
                    urls = {_path(binding['profile_url']), *(_path(u) for u in binding.get('profile_aliases', []))}
                    own = next((n.get('value') for n in around if n.get('type') == 'Hyperlink' and _path(n.get('value', '')) in urls), None)
                    if own:
                        return {'url': target, 'post_id':target.rsplit('/',1)[-1], 'visibility': 'account_visible', 'body': body,
                                'author_url': own, 'author_name': binding['name']}
            except Exception:
                pass
        raise NativeUnknown('已提交一次，但作者和完整评论回执未核实，禁止自动重发')
