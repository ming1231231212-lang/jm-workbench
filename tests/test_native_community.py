"""Local desktop contract tests; no browser or external publication."""
import pytest

from jm_workbench.community.native import NativePublisher, NativeStopped, NativeUnknown, normalized

URL = 'https://zhuanlan.zhihu.com/p/711177755'
PROFILE = 'https://www.zhihu.com/people/fixture-owner'
ALIAS = 'https://www.zhihu.com/people/11112222333344445555666677778888'
BODY = '原帖讨论先输出自己的理解。可以关闭资料，再用一道新的例题检查能否独立应用。（AI辅助整理）'
ACCOUNT = {'id': 'fixture', 'platform': 'zhihu', 'identity': 'zhihu:fixture-owner', 'enabled': True}
BINDING = {'identity': ACCOUNT['identity'], 'profile_url': PROFILE, 'name': '测试作者'}
PAYLOAD = {'kind': 'reply', 'body': BODY, 'source_title': '自主学习的具体讨论', 'source_excerpt': '先写自己的思考，再让AI整理，检查自己有没有真正理解。'}


class FakeDesktop:
    def __init__(self):
        self.url = PROFILE; self.body = ''; self.writes = 0; self.visible = False
        self.fault = ''; self.author = PROFILE; self.history = []

    def call(self, action, **kw):
        self.history.append((action, kw))
        if action == 'open': self.url = kw['url']; return {'url': self.url}
        if action == 'snapshot':
            if self.url in (PROFILE, ALIAS):
                return {'url': self.url, 'text': '测试作者 编辑个人资料', 'nodes': [{'key': 'owner', 'type': 'Button', 'name': '编辑个人资料', 'visible': True}]}
            if self.fault == 'wrong-page': return {'url': PROFILE, 'text': 'other page', 'nodes': []}
            text = PAYLOAD['source_title'] + '\n' + PAYLOAD['source_excerpt']
            nodes = [{'key': 'avatar', 'type': 'Button', 'name': '点击打开测试作者的主页', 'visible': True},
                     {'key': 'comments', 'type': 'Button', 'name': '3 条评论', 'visible': True},
                     {'key': 'editor', 'type': 'Edit', 'name': '', 'value': self.body, 'visible': True},
                     {'key': 'send', 'type': 'Button', 'name': '发布', 'visible': True, 'enabled': True}]
            if self.visible or self.fault == 'duplicate':
                text += '\n' + BODY
                nodes += [{'key': 'author', 'type': 'Hyperlink', 'name': '测试作者', 'value': self.author, 'visible': True},
                          {'key': 'comment', 'type': 'Text', 'name': BODY, 'visible': True}]
            return {'url': self.url, 'text': text, 'nodes': nodes}
        if action == 'paste': self.body = 'changed' if self.fault == 'changed-body' else kw['text']
        if action == 'click' and kw['key'] == 'send':
            self.writes += 1
            if self.fault == 'timeout': raise TimeoutError('ambiguous response')
            self.body = ''; self.visible = True
        return {}


def publisher(ui): return NativePublisher(ui, sleep=lambda _: None, poll_attempts=2)


def test_native_comment_checks_profile_source_full_body_and_receipt():
    ui = FakeDesktop()
    receipt = publisher(ui).publish(ACCOUNT, BINDING, PAYLOAD, URL)
    assert ui.writes == 1 and receipt['url'] == URL
    assert receipt['visibility'] == 'account_visible'
    assert receipt['author_url'] == PROFILE and receipt['body'] == BODY


@pytest.mark.parametrize('fault', ['wrong-page', 'changed-body', 'duplicate'])
def test_native_preflight_changes_never_submit(fault):
    ui = FakeDesktop(); ui.fault = fault
    with pytest.raises(NativeStopped): publisher(ui).publish(ACCOUNT, BINDING, PAYLOAD, URL)
    assert ui.writes == 0


def test_ambiguous_submit_is_attempted_once_and_never_retried():
    ui = FakeDesktop(); ui.fault = 'timeout'
    with pytest.raises(NativeUnknown): publisher(ui).publish(ACCOUNT, BINDING, PAYLOAD, URL)
    assert ui.writes == 1


def test_other_authors_matching_text_cannot_prove_own_submission():
    ui = FakeDesktop(); ui.author = 'https://www.zhihu.com/people/someone-else'
    with pytest.raises(NativeUnknown): publisher(ui).publish(ACCOUNT, BINDING, PAYLOAD, URL)
    assert ui.writes == 1


def test_binding_cannot_silently_replace_existing_identity():
    ui = FakeDesktop(); bad = {**BINDING, 'identity': 'a-different-person'}
    with pytest.raises(NativeStopped): publisher(ui).publish(ACCOUNT, bad, PAYLOAD, URL)
    assert ui.writes == 0


def test_normalization_only_removes_layout_artifacts():
    assert normalized('A \nB\u200b\ufffc') == 'AB'
    assert normalized('不要删除') != normalized('要删除')


def test_reservation_callback_runs_before_the_only_submit():
    ui = FakeDesktop(); reserved = []
    def reserve():
        assert ui.writes == 0
        reserved.append('durable')
    NativePublisher(ui, sleep=lambda _: None, before_submit=reserve).publish(ACCOUNT, BINDING, PAYLOAD, URL)
    assert reserved == ['durable'] and ui.writes == 1


def test_changed_reservation_prevents_submit_even_after_input():
    ui = FakeDesktop()
    def cancelled(): raise NativeStopped('user paused')
    with pytest.raises(NativeStopped):
        NativePublisher(ui, sleep=lambda _: None, before_submit=cancelled).publish(ACCOUNT, BINDING, PAYLOAD, URL)
    assert ui.writes == 0


@pytest.mark.parametrize('platform,identity,profile,node', [
    ('juejin', '1234567890123456', 'https://juejin.cn/user/1234567890123456', {'type': 'Button', 'name': '设置'}),
    ('tieba', '123456789', 'https://tieba.baidu.com/home/main?id=tb.fixture-owner', {'type': 'Hyperlink', 'name': '我的', 'value': 'https://tieba.baidu.com/home/main?id=tb.fixture-owner&fr=personpage'}),
])
def test_other_native_accounts_require_own_profile_marker(platform, identity, profile, node):
    class ReadOnly:
        def call(self, action, **kw):
            assert action in ('open', 'snapshot')
            return {'url': profile, 'text': '趣造AI', 'nodes': [{**node, 'key': 'owner', 'visible': True}]}
    a = {'id': 'fixture', 'platform': platform, 'enabled': True, 'identity': identity}
    assert NativePublisher(ReadOnly()).check(a, {'identity': identity, 'profile_url': profile, 'name': '趣造AI'}) == identity


def test_profile_shell_loading_does_not_prematurely_fail_identity():
    class Loading:
        reads=0
        def call(self,action,**kw):
            assert action in ('open','snapshot')
            if action=='snapshot':self.reads+=1
            ready=self.reads>=2
            return {'url':'https://juejin.cn/user/1234567890123456','text':'趣造AI' if ready else '首页 创作者中心',
                    'nodes':[{'type':'Button','name':'设置','visible':True}] if ready else []}
    ui=Loading();a={'platform':'juejin','enabled':True,'identity':'1234567890123456'}
    assert NativePublisher(ui,sleep=lambda _:None,poll_attempts=3).check(a,{'identity':a['identity'],'profile_url':'https://juejin.cn/user/'+a['identity'],'name':'趣造AI'})==a['identity']
    assert ui.reads==2


def test_verified_profile_alias_is_accepted_only_after_own_profile_check():
    ui = FakeDesktop(); ui.author = ALIAS
    binding = {**BINDING, 'profile_aliases': [ALIAS]}
    receipt = publisher(ui).publish(ACCOUNT, binding, PAYLOAD, URL)
    assert ui.writes == 1 and receipt['author_url'] == ALIAS
    assert any(action == 'open' and args['url'] == ALIAS for action, args in ui.history)


def test_unowned_alias_cannot_be_added_to_accept_matching_nickname():
    class Unowned(FakeDesktop):
        def call(self, action, **kw):
            value = super().call(action, **kw)
            if action == 'snapshot' and self.url == ALIAS:
                value['nodes'] = []; value['text'] = '测试作者 关注'
            return value
    ui = Unowned()
    with pytest.raises(NativeStopped): publisher(ui).publish(ACCOUNT, {**BINDING, 'profile_aliases': [ALIAS]}, PAYLOAD, URL)
    assert ui.writes == 0


def test_verified_alias_may_redirect_to_the_exact_bound_primary_profile():
    class Redirect(FakeDesktop):
        def call(self, action, **kw):
            value = super().call(action, **kw)
            if action == 'snapshot' and self.url == ALIAS: value['url'] = PROFILE
            return value
    ui = Redirect(); ui.author = ALIAS
    assert publisher(ui).publish(ACCOUNT, {**BINDING, 'profile_aliases': [ALIAS]}, PAYLOAD, URL)['author_url'] == ALIAS


def test_a_long_title_is_not_accepted_as_the_only_body_evidence():
    ui=FakeDesktop()
    bad={**PAYLOAD,"source_title":"这是一个足够长但只来自标题没有具体正文依据的测试题目","source_excerpt":"这是一个足够长但只来自标题没有具体正文依据的测试题目"}
    with pytest.raises(NativeStopped):publisher(ui).publish(ACCOUNT,BINDING,bad,URL)
    assert ui.writes==0
