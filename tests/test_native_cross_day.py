"""Reuse yesterday's result page and verify today's split article, without writes."""
import pytest
from test_native_channel import Channel
from jm_workbench.community.native import NativePublisher, NativeUnknown, NativeStopped
from jm_workbench.community.native_articles import verify_article

OLD='https://juejin.cn/spost/1234567890123456'
NEW='https://juejin.cn/post/1234567890123456'
EDITOR='https://juejin.cn/editor/drafts/new?v=2'
PROFILE='https://www.zhihu.com/people/fixture-owner'
TITLE='如何核对AI表格的来源与缺失项'
BODY='在使用AI表格时，先保留原始材料并逐项核对缺失内容，不要把推测当成事实。我维护示例网站，网站是 https://fixture.example/ 。欢迎一起检查具体问题。\n（AI辅助整理）'


def test_next_day_reuses_same_article_canonical_redirect_after_process_restart(tmp_path):
    path=tmp_path/'tab.json'
    yesterday=Channel(path,OLD);yesterday.state={'key':'owned','url':OLD};yesterday.save()
    today=Channel(path,NEW)
    today.call('open',url=EDITOR)
    assert today.live==EDITOR and today.state['url']==EDITOR
    assert [a for a,_ in today.actions].count('navigate')==1
    assert not any(a in ('new','click','paste') for a,_ in today.actions)


@pytest.mark.parametrize('live,draft',[
    ('https://juejin.cn/post/9999999999999999',False),
    ('https://other.example/post/1234567890123456',False),
    ('http://juejin.cn/post/1234567890123456',False),
    ('https://juejin.cn:444/post/1234567890123456',False),
    ('https://guest@juejin.cn/post/1234567890123456',False),
    (NEW+'?different=1',False),
    (NEW,True),
])
def test_next_day_never_overwrites_another_target_or_unresolved_draft(tmp_path,live,draft):
    ui=Channel(tmp_path/'tab.json',live);ui.state={'key':'owned','url':OLD}
    if draft:ui.state['draft']='unresolved-content'
    with pytest.raises(NativeStopped):ui.call('open',url=EDITOR)
    assert not any(a in ('navigate','new','click','paste') for a,_ in ui.actions)


def split_article(*,wrong_author=False,missing=False,hostile_link=False,header_only=False):
    def n(key,parent,type,name='',value=''):
        return dict(key=key,parent=parent,type=type,name=name,value=value,visible=True)
    nodes=[n('doc','','Document',TITLE),n('header','doc','Hyperlink','owner',PROFILE),
           n('article','doc','Group'),n('title','article','Text',TITLE),
           n('body','article','Group'),n('p1','body','Group'),
           n('a','p1','Text','在使用'),
           n('entity','p1','Hyperlink','AI表格','https://zhida.zhihu.com/search?q=AI表格'),
           n('b','p1','Text','时，先保留原始材料并逐项核对缺失内容，不要把推测当成事实。我维护'),
           n('entity2','p1','Hyperlink','示例网站','https://zhida.zhihu.com/search?q=示例网站'),
           n('c','p1','Text','，网站是 '),
           n('site','p1','Hyperlink','https://fixture.example/','https://evil.example/' if hostile_link else 'https://fixture.example/'),
           n('label','site','Text','https://fixture.example/'),
           n('d','p1','Text',' 。欢迎一起检查具体问题。'),
           n('p2','body','Text','（AI辅助整理）')]
    if not header_only:nodes.insert(4,n('author','article','Hyperlink','owner','https://www.zhihu.com/people/other' if wrong_author else PROFILE))
    if missing:nodes=[n for n in nodes if n['key']!='b']
    return {'url':'https://zhuanlan.zhihu.com/p/123456789','text':TITLE+'\n'+BODY,'nodes':nodes}


class ReadOnlyResult:
    def __init__(self,snapshot):self.snapshot=snapshot;self.actions=[]
    def call(self,action,**kwargs):
        self.actions.append(action)
        assert action=='follow_published', 'Receipt verification must not submit or navigate'
        return self.snapshot


def verify(snapshot):
    ui=ReadOnlyResult(snapshot)
    result=verify_article(NativePublisher(ui,sleep=lambda _:None,poll_attempts=1),
        {'platform':'zhihu'},{'profile_url':PROFILE,'name':'owner'},{'title':TITLE,'body':BODY})
    assert ui.actions==['follow_published']
    return result


def test_split_paragraph_with_platform_entity_links_verifies_own_article():
    receipt=verify(split_article())
    assert receipt['body']==BODY and receipt['author_url']==PROFILE
    assert receipt['visibility']=='account_visible'


@pytest.mark.parametrize('change',[{'wrong_author':True},{'missing':True},{'hostile_link':True},{'header_only':True}])
def test_header_text_cannot_hide_missing_body_wrong_author_or_destination(change):
    with pytest.raises(NativeUnknown):verify(split_article(**change))


def test_other_article_or_comment_cannot_supply_the_missing_body_fragment():
    s=split_article(missing=True)
    lost=next(n for n in split_article()['nodes'] if n['key']=='b')
    lost['parent']='doc';s['nodes'].append(lost)
    with pytest.raises(NativeUnknown):verify(s)


def test_site_header_in_generic_group_still_is_not_the_article_author():
    s=split_article(header_only=True)
    s['nodes'].insert(1,dict(key='page',parent='doc',type='Group',name='',visible=True))
    for n in s['nodes']:
        if n['key'] in ('header','article'):n['parent']='page'
    with pytest.raises(NativeUnknown):verify(s)


def test_short_text_fragments_and_inline_links_do_not_need_a_whole_paragraph_node():
    s=split_article();n=next(n for n in s['nodes'] if n['key']=='b');index=s['nodes'].index(n)
    s['nodes'][index:index+1]=[{**n,'key':'fragment'+str(i),'name':n['name'][i:i+8]} for i in range(0,len(n['name']),8)]
    assert verify(s)['body']==BODY


def test_known_result_reuse_survives_three_daily_channel_restarts(tmp_path):
    path=tmp_path/'three-days.json'
    for day in range(3):
        ident=str(1234567890123456+day);old=OLD.replace('1234567890123456',ident);new=old.replace('/spost/','/post/')
        previous=Channel(path,old);previous.state={'key':'owned','url':old};previous.save()
        current=Channel(path,new);current.call('open',url=EDITOR)
        assert current.live==EDITOR and not any(a=='new' for a,_ in current.actions)
