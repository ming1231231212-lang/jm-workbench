import pytest
import json
import subprocess
from types import SimpleNamespace

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


def native_runner(monkeypatch, result, returncode=0):
    import jm_workbench.community.native_channel as module
    monkeypatch.setattr(module.os, 'name', 'nt')
    monkeypatch.setattr(module.subprocess, 'CREATE_NO_WINDOW', 0, raising=False)
    calls = []
    def runner(command, **kw):
        calls.append((command, json.loads(kw['input'])))
        return SimpleNamespace(returncode=returncode, stdout=json.dumps(result), stderr='原日常Chrome进程已变化')
    return runner, calls


def test_verified_window_and_original_process_are_sent_on_every_call(tmp_path, monkeypatch):
    runner, calls = native_runner(monkeypatch, {'url':'https://www.zhihu.com/'})
    ui = NativeChromeChannel(tmp_path/'tab.json', runner=runner);ui.shell='powershell'
    ui.state={'key':'owned','window':134346,'process_id':12464,'process_started':'original-start'}
    ui.raw('url');ui.raw('select',key='owned')
    for command, request in calls:
        assert command[-6:]==['-Window','134346','-ExpectedProcessId','12464','-ExpectedProcessStarted','original-start']
    assert calls[0][1]['tab_key']=='owned'


def test_legacy_tab_binding_is_migrated_only_after_native_validation(tmp_path, monkeypatch):
    binding={'window':134346,'process_id':12464,'process_started':'original-start'}
    runner, calls = native_runner(monkeypatch, {'url':'https://www.zhihu.com/',**binding})
    ui=NativeChromeChannel(tmp_path/'tab.json',runner=runner);ui.shell='powershell'
    ui.state={'key':'owned','url':'https://www.zhihu.com/','draft':'kept'}
    ui.raw('url');ui.raw('url')
    assert '-Window' not in calls[0][0] and '-Window' in calls[1][0]
    saved=json.loads(ui.path.read_text(encoding='utf-8'))
    assert saved=={'key':'owned','url':'https://www.zhihu.com/','draft':'kept',**binding}


def test_failed_window_validation_never_rebinds_or_retries(tmp_path, monkeypatch):
    runner,calls=native_runner(monkeypatch,{'window':999,'process_id':99,'process_started':'new'},returncode=1)
    ui=NativeChromeChannel(tmp_path/'tab.json',runner=runner);ui.shell='powershell'
    original={'key':'owned','window':134346,'process_id':12464,'process_started':'original'}
    ui.state=original.copy();ui.save()
    with pytest.raises(NativeStopped,match='进程已变化'):ui.raw('url')
    assert len(calls)==1 and ui.state==original
    assert json.loads(ui.path.read_text(encoding='utf-8'))==original


def test_incomplete_window_binding_refuses_before_starting_native_process(tmp_path,monkeypatch):
    runner,calls=native_runner(monkeypatch,{})
    ui=NativeChromeChannel(tmp_path/'tab.json',runner=runner);ui.shell='powershell'
    ui.state={'key':'owned','window':134346}
    with pytest.raises(NativeStopped,match='绑定不完整'):ui.raw('url')
    assert calls==[]


def test_creating_tab_keeps_verified_window_binding(tmp_path):
    class Bound(Channel):
        def raw(self,action,**kw):
            if action=='new':self.state.update(window=134346,process_id=12464,process_started='original')
            return super().raw(action,**kw)
    ui=Bound(tmp_path/'tab.json','https://user.example/')
    ui.call('open',url='https://www.zhihu.com/people/fixture')
    assert ui.state['window']==134346 and ui.state['process_started']=='original'
    assert ui.state['key']=='owned'

def test_readonly_identity_replaces_repurposed_tab_in_same_window(tmp_path):
    ui=Channel(tmp_path/'tab.json','https://user.example/')
    ui.state={'key':'old','url':'https://www.zhihu.com/people/fixture','window':1,'process_id':2,'process_started':'original'}
    ui.readonly_replacement=True
    ui.call('open',url='https://www.zhihu.com/people/fixture')
    assert ui.state['key']=='owned' and ui.state['window']==1
    assert sum(a=='new' for a,_ in ui.actions)==1
    assert not any(a=='close' for a,_ in ui.actions)

def test_closed_unsent_draft_restores_from_job_without_touching_other_tabs(tmp_path):
    class Closed(Channel):
        def raw(self,action,**kw):
            if action=='select' and kw.get('key')=='closed':raise NativeStopped('标签关闭')
            return super().raw(action,**kw)
    ui=Closed(tmp_path/'tab.json','https://user.example/')
    payload={'title':'未发布标题','body':'尚未提交正文'}
    ui.state={'key':'closed','url':'https://zhuanlan.zhihu.com/write','window':1,'process_id':2,'process_started':'original','draft':ui.fingerprint(payload)}
    assert ui.resume_article(payload) is None
    ui.call('open',url='https://zhuanlan.zhihu.com/write')
    assert ui.state['key']=='owned' and ui.state['window']==1
    assert not any(a in ('click','close') for a,_ in ui.actions)
