import pytest

from jm_workbench.community.native_channel import NativeChromeChannel
from jm_workbench.community.native import NativeStopped


class Channel(NativeChromeChannel):
    def __init__(self, path, url):
        super().__init__(path); self.live = url; self.actions = []
    def raw(self, action, **kw):
        self.actions.append((action, kw))
        if action == 'url': return {'url': self.live}
        if action == 'snapshot': return {'url': self.live, 'text': 'visible' if self.live == kw.get('expected_url') else '', 'nodes': []}
        if action == 'tabs': return {'tabs': [{'key': 'owned', 'selected': True}]}
        if action == 'new': self.live = 'chrome://newtab/'
        if action == 'navigate': self.live = kw['url']
        return {}


def test_task_tab_is_created_in_existing_window_then_bound(tmp_path):
    ui = Channel(tmp_path/'tab.json', 'https://user.example/')
    ui.call('open', url='https://www.zhihu.com/people/fixture')
    assert [a for a, _ in ui.actions][:3] == ['new', 'tabs', 'url']
    assert ui.state['key'] == 'owned' and ui.state['url'].endswith('/people/fixture')


def test_repurposed_task_tab_is_not_overwritten(tmp_path):
    ui = Channel(tmp_path/'tab.json', 'https://user.example/')
    ui.state = {'key': 'owned', 'url': 'https://www.zhihu.com/'}
    with pytest.raises(NativeStopped): ui.call('open', url='https://www.zhihu.com/people/fixture')
    assert not any(a == 'navigate' for a, _ in ui.actions)


@pytest.mark.parametrize('old,new', [
    ('https://zhuanlan.zhihu.com/write','https://zhuanlan.zhihu.com/p/123456789/edit'),
    ('https://juejin.cn/editor/drafts/new?v=2','https://juejin.cn/editor/drafts/1234567890123456'),
])
def test_only_expected_editor_redirect_is_adopted(tmp_path, old, new):
    ui = Channel(tmp_path/'tab.json', new); ui.expected = old; ui.state = {'key':'owned','url':old}
    assert ui.call('follow_editor')['text'] == 'visible'
    assert ui.state['url'] == new


def test_unrelated_redirect_never_exposes_content_or_rebinds_tab(tmp_path):
    ui = Channel(tmp_path/'tab.json', 'https://user.example/private')
    ui.expected = 'https://zhuanlan.zhihu.com/write'; ui.state = {'key':'owned','url':ui.expected}
    with pytest.raises(NativeStopped): ui.call('follow_editor')
    assert not any(a == 'snapshot' for a, _ in ui.actions)


def test_published_zhihu_article_must_match_this_editor_id(tmp_path):
    ui = Channel(tmp_path/'tab.json', 'https://zhuanlan.zhihu.com/p/999999')
    ui.expected = 'https://zhuanlan.zhihu.com/p/123456/edit'; ui.state = {'key':'owned','url':ui.expected}
    with pytest.raises(NativeStopped): ui.call('follow_published')
