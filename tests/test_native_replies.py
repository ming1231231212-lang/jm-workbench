import pytest
from jm_workbench.community.native import NativePublisher,NativeStopped,NativeUnknown
from jm_workbench.community.native_replies import prepare_reply,verify_reply

BODY="原帖讨论了未知字段的处理。建议保存原文依据，缺少负责人就返回未说明，避免自行补全。（AI辅助整理）"
SOURCE="这里是原帖的具体正文，讨论未知字段处理时保留原文依据和明确的失败结果。"

class UI:
    def __init__(self,platform):
        self.platform=platform;self.url='';self.body='';self.menu=False;self.writes=0;self.author='owner';self.visible=False
        self.profile='https://tieba.baidu.com/home/main?id=tb.fixture' if platform=='tieba' else 'https://juejin.cn/user/1234567890123456'
    def n(self,key,type,name='',**kw):return {'key':key,'type':type,'name':name,'value':'','parent':'doc','visible':True,'enabled':True,**kw}
    def snapshot(self):
        n=self.n;ns=[n('doc','Document')]
        if self.url==self.profile:
            ns += [n('own','Hyperlink','我的',value=self.profile)] if self.platform=='tieba' else [n('settings','Button','设置')]
            return {'url':self.url,'text':'fixture 编辑个人资料 设置','nodes':ns}
        ns += [n('mine','Hyperlink','我的',value=self.profile),n('avatar','Image','fixture的头像'),n('placeholder','Text','参与讨论涨经验'),n('root','Group',id='tb-editor-pb-content' if self.platform=='tieba' else 'comment-box'),n('edit','Group',parent='root',text_input=True,focusable=True,value=self.body),n('send','Button','发布' if self.platform=='tieba' else '发送')]
        if self.menu:ns += [n('menu-user','Hyperlink','fixture',value=self.profile)]
        if self.visible:ns += [n('row','Group'),n('author','Hyperlink','fixture',parent='row',value=self.profile if self.author=='owner' else 'https://juejin.cn/user/9999999999999999'),n('comment','Text',BODY,parent='row')]
        return {'url':self.url,'text':'原帖标题\n'+SOURCE,'nodes':ns}
    def call(self,action,**kw):
        if action=='open':self.url=kw['url'];return {}
        if action in ('snapshot','follow_editor'):return self.snapshot()
        if action=='keys':return {}
        if action=='focus-copy':return {'value':self.body}
        if action=='focus-paste':self.body=kw['text'];return {'value':self.body}
        if action=='click':
            if kw['key']=='avatar':self.menu=not self.menu
            if kw['key']=='send':self.writes+=1;self.body='';self.visible=True
            return {}
        raise AssertionError(action)

@pytest.mark.parametrize('platform',['tieba','juejin'])
def test_native_reply_verifies_source_owner_and_full_body_before_single_write(platform):
    ui=UI(platform);binding={'identity':'1234567890123456' if platform=='juejin' else 'fixture','profile_url':ui.profile,'name':'fixture'}
    a={'platform':platform,'identity':binding['identity'],'enabled':True};payload={'kind':'reply','body':BODY,'source_title':'原帖标题','source_excerpt':SOURCE}
    url='https://tieba.baidu.com/p/123456789' if platform=='tieba' else 'https://juejin.cn/post/1234567890123456789'
    receipt=NativePublisher(ui,sleep=lambda _:None).publish(a,binding,payload,url)
    assert ui.writes==1 and receipt['author_url']==ui.profile and receipt['visibility']=='account_visible'

@pytest.mark.parametrize('platform',['tieba','juejin'])
def test_existing_native_reply_draft_is_preserved(platform):
    ui=UI(platform);ui.body='my existing draft';p=NativePublisher(ui,sleep=lambda _:None)
    a={'platform':platform};binding={'profile_url':ui.profile,'name':'fixture'};payload={'kind':'reply','body':BODY,'source_title':'原帖标题','source_excerpt':SOURCE}
    url='https://tieba.baidu.com/p/123456789' if platform=='tieba' else 'https://juejin.cn/post/1234567890123456789'
    with pytest.raises(NativeStopped,match='保留'):prepare_reply(p,a,binding,payload,url)
    assert ui.writes==0 and ui.body=='my existing draft'


def test_matching_text_from_other_author_cannot_prove_native_reply():
    ui=UI('juejin');ui.visible=True;ui.author='other';ui.url='https://juejin.cn/post/1234567890123456789'
    with pytest.raises(NativeUnknown):verify_reply(NativePublisher(ui,sleep=lambda _:None,poll_attempts=2),{'platform':'juejin'},{'profile_url':ui.profile,'name':'fixture'},{'body':BODY},{'url':ui.url})
