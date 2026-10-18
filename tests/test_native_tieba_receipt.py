"""Tieba exposes the article as flat document children; verification stays read-only."""
import pytest
from jm_workbench.community.native import NativePublisher, NativeUnknown
from jm_workbench.community.native_articles import verify_article

PROFILE='https://tieba.baidu.com/home/main?id=tb.1.fixture'
TITLE='整理AI资料先核对原始链接'
BODY='第一段需要完整保留原文和具体核验条件。\n第二段说明自己的操作步骤和实际限制。\n本文使用AI辅助整理。'

def snapshot():
    def n(key,type,name='',value='',parent='doc',rect=None):
        return dict(key=key,parent=parent,type=type,name=name,value=value,visible=True,rect=rect or [600,300,500,40])
    nodes=[n('doc','Document',TITLE+'-百度贴吧',parent=''),
        n('menu','Hyperlink','我的',PROFILE,rect=[30,100,200,40]),
        n('owner','Hyperlink','fixture',PROFILE+'&fr=pb',rect=[670,220,100,35]),
        n('owner-child','Hyperlink','fixture',PROFILE+'&fr=pb',parent='owner',rect=[670,220,100,35]),
        n('stamp','Text','刚刚'),n('title-group','Group'),
        n('title','Text',TITLE,parent='title-group'),
        *[n('body'+str(i),'Text',line,rect=[600,360+i*60,800,50]) for i,line in enumerate(BODY.split('\n'))],
        n('share','Text','转发'),n('reply','Hyperlink','回复','https://tieba.baidu.com/p/123456789?showComment=1&fr=pb'),
        n('comments','Text','全部回复')]
    return dict(url='https://tieba.baidu.com/p/123456789',text=TITLE+'\n'+BODY,nodes=nodes)

def verify(s):
    class ReadOnly:
        def call(self,action,**kw):
            assert action=='follow_published'
            return s
    return verify_article(NativePublisher(ReadOnly(),sleep=lambda _:None,poll_attempts=1),
        {'platform':'tieba'},{'profile_url':PROFILE,'name':'fixture'},dict(title=TITLE,body=BODY))

def test_flat_tieba_article_verifies_body_and_post_author_before_title():
    result=verify(snapshot())
    assert result['author_url']==PROFILE+'&fr=pb' and result['body']==BODY

@pytest.mark.parametrize('change',['wrong_author','header_only','missing_body','comment_body','wrong_title','wrong_name','sidebar_owner','wrong_host'])
def test_flat_tieba_rejects_incomplete_or_unrelated_author_evidence(change):
    s=snapshot()
    if change=='wrong_author':
        for n in s['nodes']:
            if n['key'].startswith('owner'):n['value']=n['value'].replace('fixture','other')
    if change=='header_only':s['nodes']=[n for n in s['nodes'] if not n['key'].startswith('owner')]
    if change in ('missing_body','comment_body'):
        removed=next(n for n in s['nodes'] if n['key']=='body1');s['nodes'].remove(removed)
        if change=='comment_body':s['nodes'].append(removed)
    if change=='wrong_title':next(n for n in s['nodes'] if n['key']=='title')['name']='另一篇内容'
    if change=='wrong_name':
        for n in s['nodes']:
            if n['key'].startswith('owner'):n['name']='other'
    if change=='sidebar_owner':
        for n in s['nodes']:
            if n['key'].startswith('owner'):n['rect']=[30,100,100,35]
    if change=='wrong_host':s['url']='https://example.com/p/123456789'
    with pytest.raises(NativeUnknown):verify(s)
