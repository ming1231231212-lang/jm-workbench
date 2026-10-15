"""Article preparation is tested without contacting a platform or submitting."""
import pytest

from jm_workbench.community.native import NativePublisher, NativeStopped
from jm_workbench.community.native_articles import prepare_article, inside, rendered, author_scope, verify_article, semantic_value
from jm_workbench.community.native import NativeUnknown, profile_key


class ArticleUI:
    def __init__(self, platform):
        self.platform = platform; self.url = ''; self.title = ''; self.body = ''
        self.popup = False; self.search = ''; self.summary = ''; self.tags = []
        self.ai = False; self.menu = False; self.topic_input = False; self.category = ''
        self.writes = 0; self.overwritten = False; self.fail_tags = False
    def node(self, key, type, name='', **kw):
        return {'key':key,'type':type,'name':name,'parent':'panel','visible':True,'enabled':True,'value':'',**kw}
    def snapshot(self):
        n = self.node; p = self.platform
        nodes = [n('panel','Group')]
        if p == 'tieba':
            nodes += [n('troot','Group',id='tb-editor-title'),n('broot','Group',id='tb-editor-content'),
                n('title','Group',parent='troot',text_input=True,focusable=True,value=self.title),
                n('body','Group',parent='broot',text_input=True,focusable=True,value=self.body),
                n('board-label','Text','发布到吧'),n('board','Text','ai工具'),
                n('ai-row','Group',checked='On' if self.ai else 'Off'),n('ai','Text','贴子含AI内容',parent='ai-row'),
                n('publish','Text','发布')]
        elif p == 'juejin':
            nodes += [n('title','Edit','输入文章标题...',value=self.title),
                n('body','Edit',visible=False,focusable=True,value=self.body),n('publish','Button','发布')]
            if self.popup:
                nodes += [n('category-label','Text','分类'),n('category','Text','人工智能',selected=self.category=='人工智能'),
                    n('tag-label','Text','请搜索添加标签'),n('tag-search','Edit','搜索标签',value=self.search,rect=[0,0,200,30]),
                    n('summary','Edit','请输入摘要',value=self.summary,rect=[0,0,300,120]),
                    n('confirm','Button','确定并发布')]
                if self.search and not self.fail_tags: nodes += [n('tag-option','ListItem',self.search)]
                nodes += [n('chip-'+t,'Group') for t in self.tags]
                nodes += [n('selected-'+t,'Text',t,parent='chip-'+t) for t in self.tags]
        else:
            nodes += [n('title','Edit',value=self.title),n('body','Edit',value=self.body),
                n('settings','Button','发布设置'),n('publish','Button','发布')]
            if self.popup:
                nodes += [n('declaration','Text','包含 AI 辅助创作 作者对内容负责' if self.ai else '无声明'),
                    n('add-topic','Button','添加话题')]
                if self.menu: nodes += [n('ai-option','ListItem','包含 AI 辅助创作 作者对内容负责')]
                if self.topic_input: nodes += [n('tag-search','Edit','搜索话题',value=self.search)]
                if self.search and not self.fail_tags: nodes += [n('tag-option','Button',self.search)]
                nodes += [n('selected-'+t,'Text',t) for t in self.tags]
        return {'url':self.url,'text':'发布文章 '+self.title+'\n'+self.body+'\n'+' '.join(self.tags),'nodes':nodes}
    def call(self, action, **kw):
        if action == 'open': self.url=kw['url']; return {}
        if action in ('snapshot','follow_editor'): return self.snapshot()
        if action == 'focus-copy': return {'value':getattr(self,kw['key'])}
        if action in ('paste','focus-paste'):
            key=kw['key']; value=kw['text']
            if key in ('title','body'):
                if getattr(self,key):self.overwritten=True
                setattr(self,key,value)
            elif key=='tag-search':self.search=value
            elif key=='summary':self.summary=value
            return {'value':value}
        if action == 'checkbox': return {'checked':self.ai}
        if action == 'selected': return {'selected':self.category=='人工智能'}
        if action == 'click':
            key=kw['key']
            if key in ('settings','publish'):self.popup=True
            elif key=='declaration':self.menu=True
            elif key in ('ai-option','ai'):self.ai=True;self.menu=False
            elif key=='add-topic':self.topic_input=True;self.search=''
            elif key=='tag-option':self.tags.append(self.search);self.search='';self.topic_input=False
            elif key=='category':self.category='人工智能'
            return {}
        raise AssertionError(action)


@pytest.mark.parametrize('platform,board,tags', [('zhihu','',['人工智能','AI工具']),('juejin','人工智能',['人工智能','AI编程']),('tieba','ai工具',[])])
def test_native_article_prepares_full_text_tags_and_disclosure_without_submitting(platform,board,tags):
    ui=ArticleUI(platform); p=NativePublisher(ui,sleep=lambda _:None)
    payload={'title':'如何核对AI任务结果','body':'说明：本文使用AI辅助整理。\n\n先用一份能够自己判断对错的材料试用，再记录输入、输出、来源和未知项。','platform_tags':tags,'kind':'thread'}
    ready=prepare_article(p,{'platform':platform},{'name':'fixture'},payload,board)
    assert ui.title==payload['title'] and ui.body==payload['body'] and not ui.overwritten
    assert ready['submit']['key']==('confirm' if platform=='juejin' else 'publish')
    assert ui.writes==0
    if platform!='juejin': assert ui.ai
    if tags: assert ui.tags==tags


@pytest.mark.parametrize('platform,board', [('zhihu',''),('juejin','人工智能'),('tieba','ai工具')])
def test_existing_article_draft_is_preserved(platform,board):
    ui=ArticleUI(platform);ui.body='existing personal draft'
    with pytest.raises(NativeStopped):
        prepare_article(NativePublisher(ui,sleep=lambda _:None),{'platform':platform},{'name':'fixture'}, {'title':'测试标题','body':'说明：本文使用AI辅助整理。至少保留一份独立输入输出样本。','platform_tags':['人工智能']},board)
    assert ui.body=='existing personal draft' and not ui.overwritten and ui.writes==0


@pytest.mark.parametrize('error',['其他窗口遮挡目标控件，未点击','目标标签已变化，未操作'])
def test_tieba_uses_second_composer_only_when_first_was_occluded(error):
    class Overlay(ArticleUI):
        opened=False;attempted=[]
        def snapshot(self):
            if self.opened:return super().snapshot()
            return {'url':self.url,'text':'ai工具吧','nodes':[self.node('global','Text','发贴'),self.node('inline','Text','发贴')]}
        def call(self,action,**kw):
            if action=='click' and kw.get('key') in ('global','inline'):
                self.attempted.append(kw['key'])
                if kw['key']=='global':raise NativeStopped(error)
                self.opened=True;return {}
            return super().call(action,**kw)
    ui=Overlay('tieba');p=NativePublisher(ui,sleep=lambda _:None)
    payload={'title':'核对AI任务结果','body':'说明：本文使用AI辅助整理。保留完整原始输入输出与未知项。','platform_tags':[]}
    if '遮挡' in error:
        result=prepare_article(p,{'platform':'tieba'},{'name':'fixture'},payload,'ai工具')
        assert result['submit']['key']=='publish' and ui.attempted==['global','inline']
    else:
        with pytest.raises(NativeStopped):prepare_article(p,{'platform':'tieba'},{'name':'fixture'},payload,'ai工具')
        assert ui.attempted==['global'] and not ui.body


@pytest.mark.parametrize('platform,board', [('zhihu',''),('juejin','人工智能')])
def test_missing_native_tag_option_stops_before_submission(platform,board):
    ui=ArticleUI(platform);ui.fail_tags=True
    with pytest.raises(NativeStopped):
        prepare_article(NativePublisher(ui,sleep=lambda _:None,poll_attempts=2),{'platform':platform},{'name':'fixture'},{'title':'测试标题','body':'说明：本文使用AI辅助整理。必须核对实际标签和完整正文。','platform_tags':['人工智能']},board)
    assert ui.writes==0


def test_scope_does_not_match_controls_outside_the_publisher():
    s={'nodes':[{'key':'root','parent':''},{'key':'other','parent':'root'},{'key':'panel','parent':'root'},{'key':'submit','parent':'panel'}]}
    assert inside(s,'submit','panel') and not inside(s,'other','panel')


def test_juejin_existing_ai_tools_material_uses_verified_parent_tag_and_preserves_snapshot():
    ui=ArticleUI('juejin');p=NativePublisher(ui,sleep=lambda _:None)
    payload={'title':'核对AI翻译中的数字','body':'说明：本文使用AI辅助整理。核对数字与人名。',
             'platform_tags':['人工智能','AI工具']}
    ready=prepare_article(p,{'platform':'juejin'},{},payload,'人工智能')
    assert ui.tags==ready['platform_tags']==['人工智能']
    assert payload['platform_tags']==['人工智能','AI工具']
    assert ui.body==payload['body'] and not ui.overwritten and ui.writes==0


def test_juejin_unknown_tag_is_not_silently_removed():
    ui=ArticleUI('juejin');ui.fail_tags=True
    with pytest.raises(NativeStopped,match='实际标签选项未核对'):
        prepare_article(NativePublisher(ui,sleep=lambda _:None,poll_attempts=1),{'platform':'juejin'},{},
          {'title':'核对文章标签','body':'说明：本文使用AI辅助整理。','platform_tags':['未核实标签']},'人工智能')
    assert not ui.tags and ui.writes==0


def test_delayed_rich_editor_readback_rechecks_without_pasting_twice():
    class Delayed(ArticleUI):
        pastes=0
        def call(self,action,**kw):
            result=super().call(action,**kw)
            if action=='focus-paste':
                self.pastes+=1
                return {'value':'clipboard conversion pending'}
            return result
    ui=Delayed('tieba');p=NativePublisher(ui,sleep=lambda _:None)
    payload={'title':'核对AI任务结果','body':'说明：本文使用AI辅助整理。完整保存原始输入、输出和未知项。','platform_tags':[]}
    prepare_article(p,{'platform':'tieba'},{'name':'fixture'},payload,'ai工具')
    assert ui.pastes==2 and ui.title==payload['title'] and ui.body==payload['body']
    assert not ui.overwritten


def test_rendered_proof_keeps_negation_and_removes_only_markdown_layout():
    assert rendered('## 标题\n\n- 不要删除原文件')=='标题不要删除原文件'
    assert rendered('不要删除')!=rendered('要删除')


def test_category_click_without_selected_state_cannot_pass():
    class Ignored(ArticleUI):
        def call(self, action, **kw):
            if action=='click' and kw.get('key')=='category':return {}
            return super().call(action,**kw)
    ui=Ignored('juejin')
    with pytest.raises(NativeStopped,match='分类未选定'):
        prepare_article(NativePublisher(ui,sleep=lambda _:None),{'platform':'juejin'},{'name':'fixture'},{'title':'测试文章标题','body':'说明：本文使用AI辅助整理。核对实际分类是否选择成功。','platform_tags':['人工智能']},'人工智能')
    assert ui.writes==0


def test_zhihu_title_above_viewport_is_still_verified_before_submit():
    class Scrolled(ArticleUI):
        def snapshot(self):
            value=super().snapshot()
            if self.body:
                for n in value['nodes']:
                    if n['key']=='title':n['visible']=False
            return value
    ui=Scrolled('zhihu')
    prepare_article(NativePublisher(ui,sleep=lambda _:None),{'platform':'zhihu'},{'name':'fixture'},{'title':'测试文章标题','body':'说明：本文使用AI辅助整理。完整正文粘贴后编辑页已滚动。','platform_tags':['人工智能']},'')
    assert ui.title=='测试文章标题' and ui.writes==0


def result_snapshot(profile, title, body, *, other=False):
    return {'url':'https://zhuanlan.zhihu.com/p/123456789','text':title+'\n'+body,'nodes':[
        {'key':'doc','parent':'','type':'Document','name':title,'visible':True},
        {'key':'header-own','parent':'doc','type':'Hyperlink','name':'fixture','value':profile,'visible':True},
        {'key':'article','parent':'doc','type':'Group','name':title,'visible':True},
        {'key':'author','parent':'article','type':'Hyperlink','name':'fixture','value':('https://www.zhihu.com/people/someone-else' if other else profile),'visible':True},
        *[{'key':'para'+str(i),'parent':'article','type':'Text','name':line,'visible':True} for i,line in enumerate(body.split('\n')) if line]
    ]}


def test_article_author_is_checked_inside_its_content_not_the_signed_in_header():
    profile='https://www.zhihu.com/people/fixture'
    body='这是一段用于核对文章完整内容的原始正文，包含明确的来源和验收范围。'
    binding={'profile_url':profile,'name':'fixture'}
    assert author_scope(result_snapshot(profile,'标题',body),binding,body)==profile
    assert author_scope(result_snapshot(profile,'标题',body,other=True),binding,body) is None


def test_tieba_profile_query_id_cannot_be_dropped_from_author_check():
    assert profile_key('https://tieba.baidu.com/home/main?id=tb.first&fr=personpage')=='tieba:tb.first'
    assert profile_key('https://tieba.baidu.com/home/main?id=tb.first')!=profile_key('https://tieba.baidu.com/home/main?id=tb.second')


def test_published_article_receipt_requires_full_content_and_own_author():
    profile='https://www.zhihu.com/people/fixture';title='测试发布内容的完整性'
    body='说明：本文使用AI辅助整理。这里使用足够长的正文来检查来源、未知项和自己的判断依据。'
    class Result:
        def call(self, action, **kw):
            assert action=='follow_published'
            return result_snapshot(profile,title,body)
    receipt=verify_article(NativePublisher(Result(),sleep=lambda _:None),{'platform':'zhihu'},{'profile_url':profile,'name':'fixture'},{'title':title,'body':body})
    assert receipt['post_id']=='123456789' and receipt['visibility']=='account_visible'


def test_missing_published_paragraph_never_claims_success():
    profile='https://www.zhihu.com/people/fixture';title='测试发布内容的完整性'
    body='这是一段实际可以在原帖页面中读到的完整正文，测试保留原始的否定条件。'
    class Result:
        def call(self, action, **kw): return result_snapshot(profile,title,body)
    with pytest.raises(NativeUnknown):
        verify_article(NativePublisher(Result(),sleep=lambda _:None,poll_attempts=2),{'platform':'zhihu'},{'profile_url':profile,'name':'fixture'},{'title':title,'body':body+'\n这段正文实际没有发布，不能仅因标题正确而声称全部成功。'})


def test_quill_link_label_is_verified_using_its_exact_destination():
    s={'nodes':[
        {'key':'root','parent':'','type':'Document','name':'','value':''},
        {'key':'body','parent':'root','type':'Group','name':'','value':''},
        {'key':'text1','parent':'body','type':'Text','name':'网站是网页链接这个词，以及','value':''},
        {'key':'link','parent':'body','type':'Hyperlink','name':'网页链接','value':'https://fixture.example/'},
        {'key':'label','parent':'link','type':'Text','name':'网页链接','value':''},
        {'key':'text2','parent':'body','type':'Text','name':'，请核对来源。','value':''},
        {'key':'unrelated','parent':'root','type':'Hyperlink','name':'网页链接','value':'https://other.example/'},
    ]}
    value=semantic_value(s,'body','网站是网页链接这个词，以及\ufeff网页链接\ufeff，请核对来源。')
    assert value=='网站是网页链接这个词，以及https://fixture.example/，请核对来源。'
    s['nodes'][3]['value']='https://evil.example/'
    assert semantic_value(s,'body',value)!=value


def test_empty_editor_placeholder_is_not_mistaken_for_a_saved_draft():
    s={'nodes':[{'key':'body','parent':'','type':'Group','name':'','value':''},{'key':'hint','parent':'body','type':'Text','name':'请输入正文','value':''}]}
    assert semantic_value(s,'body','')==''


def test_copied_tieba_link_uses_data_url_without_trusting_its_label():
    html='<html><!--StartFragment--><p>网站：<a class="blot-link"><span class="editor-blot-link" data-url="https://fixture.example/">网页链接</span></a>。</p><!--EndFragment--></html>'
    assert semantic_value({"nodes":[]},"body","网站：网页链接。",html)=="网站：https://fixture.example/。"
    with pytest.raises(NativeStopped):semantic_value({"nodes":[]},"body","网站：网页链接。",html.replace('data-url="https://fixture.example/"','data-url="javascript:alert(1)"'))


def test_regular_clipboard_html_preserves_actual_link_destination():
    html='<!--StartFragment--><p>正文<a href="https://fixture.example/">说明文字</a>末尾</p><!--EndFragment-->'
    assert semantic_value({"nodes":[]},"body","正文说明文字末尾",html)=="正文https://fixture.example/末尾"


def test_owned_partial_draft_resumes_only_the_exact_saved_title():
    class Owned(ArticleUI):
        def resume_article(self,payload):return self.snapshot()
    ui=Owned('zhihu');ui.url='https://zhuanlan.zhihu.com/p/123456789/edit';ui.title='如何核对AI任务结果'
    prepare_article(NativePublisher(ui,sleep=lambda _:None),{'platform':'zhihu'},{'name':'fixture'},{'title':ui.title,'body':'说明：本文使用AI辅助整理。这里继续填写同一个已保存任务的完整正文。','platform_tags':['人工智能']},'')
    assert not ui.overwritten
    ui.title='other draft'
    with pytest.raises(NativeStopped):prepare_article(NativePublisher(ui,sleep=lambda _:None),{'platform':'zhihu'},{'name':'fixture'},{'title':'如何核对AI任务结果','body':'说明：本文使用AI辅助整理。不得覆盖这份不同标题的草稿。','platform_tags':['人工智能']},'')


def test_owned_existing_draft_waits_for_readback_without_overwriting():
    class Loading(ArticleUI):
        title_reads=0;pastes=0
        def resume_article(self,payload):return self.snapshot()
        def call(self,action,**kw):
            if action=='focus-copy' and kw['key']=='title':
                self.title_reads+=1
                if self.title_reads==1:return {'value':''}
            if action in ('focus-paste','paste'):self.pastes+=1
            return super().call(action,**kw)
    ui=Loading('tieba');ui.url='https://tieba.baidu.com/f?kw=ai工具';ui.title='核对AI任务结果';ui.body='说明：本文使用AI辅助整理。完整保存来源和输入输出。'
    prepare_article(NativePublisher(ui,sleep=lambda _:None),{'platform':'tieba'},{'name':'fixture'},{'title':ui.title,'body':ui.body,'platform_tags':[]},'ai工具')
    assert ui.pastes==0 and not ui.overwritten


def test_juejin_success_short_link_opens_original_and_checks_full_body():
    profile='https://juejin.cn/user/1234567890123456';title='核对AI任务结果';body='这是带有完整具体内容的原始正文，核验原始输入输出和未知项，不能只根据发布成功提示判为已完成。'
    class Result:
        opened=False;links=[]
        def call(self,action,**kw):
            if action=='open':self.links.append(kw['url']);self.opened=True;return {}
            assert action in ('snapshot','follow_published')
            if not self.opened:return {'url':'https://juejin.cn/published','text':'《'+title+'》 发布成功', 'nodes':[{'key':'result-title','type':'Hyperlink','name':'《'+title+'》','visible':True,'value':'https://juejin.cn/spost/1234567890123456'}]}
            value=result_snapshot(profile,title,body);value['url']='https://juejin.cn/post/1234567890123456';return value
    ui=Result();r=verify_article(NativePublisher(ui,sleep=lambda _:None),{'platform':'juejin'},{'profile_url':profile,'name':'fixture'},{'title':title,'body':body})
    assert ui.links==['https://juejin.cn/spost/1234567890123456'] and r['visibility']=='account_visible' and r['body']==body


def test_platform_link_wrapper_and_profile_subpages_keep_the_actual_identity():
    from jm_workbench.community.native_articles import link_destination
    assert link_destination('https://tieba.baidu.com/mo/q/checkurl?url=https%3A%2F%2Ffixture.example%2F&urlrefer=opaque')=='https://fixture.example/'
    assert profile_key('https://juejin.cn/user/1234567890123456/posts')==profile_key('https://juejin.cn/user/1234567890123456')
    assert profile_key('https://juejin.cn/user/9999999999999999/posts')!=profile_key('https://juejin.cn/user/1234567890123456')
    assert link_destination('https://other.example/mo/q/checkurl?url=https%3A%2F%2Ffixture.example%2F').startswith('https://other.example/')


def test_visible_url_text_does_not_prove_a_different_link_destination():
    profile='https://www.zhihu.com/people/fixture';title='网页链接核验';body='这里核对网站链接的实际目的地，不能只相信显示出来的文字 https://fixture.example/ 。'
    class Result:
        def call(self,action,**kw):
            s=result_snapshot(profile,title,body);s['nodes'].append({'key':'url','parent':'article','type':'Hyperlink','visible':True,'name':'https://fixture.example/','value':'https://evil.example/'})
            return s
    with pytest.raises(NativeUnknown):verify_article(NativePublisher(Result(),sleep=lambda _:None,poll_attempts=2),{'platform':'zhihu'},{'profile_url':profile,'name':'fixture'},{'title':title,'body':body})


def test_published_literal_website_url_keeps_full_body_and_author_verification():
    profile='https://www.zhihu.com/people/fixture';title='网站使用方法'
    body='这里核对网站的来源、实际使用条件和完整的使用方法，网址 https://fixture.example/ 。'
    class Result:
        def call(self,action,**kw):return result_snapshot(profile,title,body)
    receipt=verify_article(NativePublisher(Result(),sleep=lambda _:None),{'platform':'zhihu'},{'profile_url':profile,'name':'fixture'},{'title':title,'body':body})
    assert receipt['body']==body and receipt['author_url']==profile


def test_tieba_result_can_be_found_from_verified_owner_when_board_stays_stale():
    profile='https://tieba.baidu.com/home/main?id=tb.fixture';title='发表后的原帖核对'
    body='说明：这是已发表的完整正文，必须同时验证对应作者与实际文章链接，不能只看成功提示。'
    target='https://tieba.baidu.com/p/123456789'
    class Board:
        def call(self,action,**kw):
            assert action=='follow_published'
            return {'url':'https://tieba.baidu.com/f?kw=fixture','text':'旧列表','nodes':[]}
    class Owner:
        checked=False;opened=[]
        def call(self,action,**kw):
            assert self.checked
            if action=='open':self.opened.append(kw['url']);return {}
            if not self.opened:return {'url':profile,'text':title,'nodes':[{'key':'new','type':'Hyperlink','name':title,'value':target,'visible':True}]}
            s=result_snapshot(profile,title,body);s['url']=target;return s
    owner=Owner();p=NativePublisher(Board(),identity_ui=owner,sleep=lambda _:None,poll_attempts=3)
    p.check=lambda *_:setattr(owner,'checked',True)
    receipt=verify_article(p,{'platform':'tieba'},{'profile_url':profile,'name':'fixture'},{'title':title,'body':body})
    assert receipt['url']==target and owner.opened==[target]
