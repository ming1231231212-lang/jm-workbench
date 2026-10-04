import json
from datetime import datetime
from urllib.parse import urlencode
import pytest

from jm_workbench.web.app import create_app
from jm_workbench.community.models import CommunityAccount, CommunityPost, DailyPlan
from jm_workbench.community.service import SHANGHAI
from jm_workbench.community.registry import csdn_thread_url, compose_url
from jm_workbench.community.csdn import SubmitGuard, receipt, response_receipt, validate_payload
from jm_workbench.community.adapters import NotSubmitted

URL = 'https://blog.csdn.net/source_author/article/details/123456789'


def article(i=0):
    return {'title': '资料整理的验收步骤' + str(i), 'body': 'AI辅助整理。' + '先明确输入与输出，未给定的信息保留未知，使用同一份样本核对。' * 10 + str(i), 'platform_tags': ['人工智能']}


class Fake:
    def __init__(self): self.sent = []; self.fail = None
    def check(self, a, secret): return 'test_author'
    def publish(self, a, secret, payload, target):
        self.sent.append((a['platform'], payload, target))
        if self.fail: raise self.fail
        return {'post_id': '123456789', 'url': target if payload.get('kind') == 'reply' else 'https://blog.csdn.net/test_author/article/details/123456789'}
    def discover(self, *args): raise AssertionError('unverified discovery must not run')


@pytest.fixture
def setup(tmp_path):
    f = Fake(); s = create_app(tmp_path, worker=False, community_adapter=f).state.community
    n = [datetime(2026, 10, 4, 10, tzinfo=SHANGHAI).timestamp()]; s.clock = lambda: n[0]
    a = s.save_account(CommunityAccount(name='CSDN test', platform='csdn'))['id']; s.check_account(a)
    return s, f, a, n


def plan(a):
    return DailyPlan(name='CSDN daily', account_id=a, board='博客', rules_note='按原文选择技术讨论，展示完整内容及回执，不发布推广链接。',
        topics=[article()], replies=[{'url':URL[:-1]+str(i),'title':'原文标题'+str(i),'excerpt':'原文讨论输入输出与模型的验收方法。','body':'AI辅助整理：这里可以先保留同一个输入样本，再核对各字段有没有来源，缺少来源时标为未知。'+str(i)} for i in range(7)])


def test_daily_creates_one_article_five_distinct_comments_once(setup):
    s,f,a,n=setup;p=s.daily.save(plan(a))['id'];s.daily.control(p,'enable');s.daily.prepare(p);s.daily.prepare(p,True)
    posts=s.state()['posts'];assert len(posts)==6 and not f.sent
    assert len({p['payload']['targets'][0]['destination'] for p in posts if p['payload']['kind']=='reply'})==5
    assert next(p for p in posts if p['payload']['kind']=='thread')['payload']['platform_tags']==['人工智能']
    assert s.sync_account(a)['status']=='verified'


def test_shared_spacing_and_daily_budget_with_account_aliases(setup):
    s,f,a,n=setup;p=s.daily.save(plan(a))['id'];s.daily.control(p,'enable');s.daily.prepare(p)
    for _ in range(6):s.tick();n[0]+=1801
    assert len(f.sent)==6
    alias=s.save_account(CommunityAccount(name='alias',platform='csdn'))['id'];s.check_account(alias)
    post=s.save(CommunityPost(request_id='extra-csdn-reply',title='另一个目标评论',kind='reply',body='AI辅助整理：这是当天第六条不同目标的评论，应当被跨账号共享的预算推迟。',targets=[{'account_id':alias,'destination':URL[:-1]+'8'}]))['id']
    s.launch(post);s.tick();assert len(f.sent)==6 and s.jobs(post)[0]['state']=='queued'


def test_unknown_outcome_does_not_retry_or_pause_other_platform(setup):
    s,f,a,n=setup;p=s.daily.save(plan(a))['id'];s.daily.control(p,'enable');f.fail=TimeoutError()
    other=s.save_account(CommunityAccount(name='juejin',platform='juejin'))['id'];s.check_account(other)
    jp=s.daily.save(DailyPlan(name='jj',account_id=other,board='人工智能',rules_note='相关内容的测试计划，不使用真实平台发送内容'))['id'];s.daily.control(jp,'enable')
    s.tick();n[0]+=3600;s.tick()
    assert len(f.sent)==1 and s.daily.get(p)['state']=='paused' and s.daily.get(jp)['state']=='enabled'


def test_duplicate_target_and_body_are_reserved(setup):
    s,f,a,n=setup;p=s.daily.save(plan(a))['id'];s.daily.control(p,'enable');s.daily.prepare(p)
    original=next(p['payload'] for p in s.state()['posts'] if p['payload']['kind']=='reply')
    for data in [{**original,'body':'AI辅助整理：更换措辞仍不能评论已经占位的目标，需要保持相同目标去重。'}, {**original,'targets':[{'account_id':a,'destination':URL[:-1]+'9'}]}]:
        data['request_id']='duplicate-'+str(len(s.state()['posts']));i=s.save(CommunityPost(**data))['id']
        with pytest.raises(ValueError,match='重复'):s.launch(i)
    assert not f.sent


def test_unverified_discovery_is_rejected_explicitly(setup):
    s,f,a,n=setup;data=plan(a).model_dump();data['source_boards']=['Agent']
    with pytest.raises(ValueError,match='自动查找'):s.daily.save(DailyPlan(**data))


@pytest.mark.parametrize('url',['http://blog.csdn.net/author/article/details/123456','https://blog.csdn.net.evil/author/article/details/123456','https://u@blog.csdn.net/author/article/details/123456','https://editor.csdn.net/md/','https://blog.csdn.net/author/article/details/123456/extra'])
def test_url_validation(url):
    with pytest.raises(ValueError):csdn_thread_url(url)


def test_url_canonicalization_and_compose():
    assert csdn_thread_url(URL+'?x=1#comments')==URL
    assert compose_url('csdn',URL)==URL


def test_payload_checks_disclosure_marketing_and_tags():
    d=article();validate_payload(d,'博客')
    for change in [{'body':d['body'].replace('AI辅助','自动')},{'body':d['body']+' quzaoai.com'},{'platform_tags':[]}]:
        with pytest.raises(ValueError):validate_payload({**d,**change},'博客')
    with pytest.raises(ValueError):validate_payload(d,'创建新专栏')


def test_receipts_require_ids_and_matching_author():
    assert receipt({'code':200,'data':12345678},'reply',URL,'test_author')['comment_id']=='12345678'
    assert receipt({'code':200,'data':{'id':123456789,'url':'https://blog.csdn.net/test_author/article/details/123456789'}},'thread','博客','test_author')['post_id']=='123456789'
    for data in [{'code':200,'data':None},{'data':12345678},{'code':200,'data':True}]:
        with pytest.raises(RuntimeError):receipt(data,'reply',URL,'test_author')
    with pytest.raises(NotSubmitted):receipt({'code':403,'message':'blocked'},'reply',URL,'test_author')
    with pytest.raises(RuntimeError):receipt({'code':200,'data':{'id':123456789,'url':URL}},'thread','博客','test_author')


class Route:
    def __init__(self,raw):self.request=type('Req',(),{'method':'POST','post_data':raw})();self.result=''
    def fallback(self):self.result='sent'
    def abort(self,*args):self.result='blocked'


@pytest.mark.parametrize('status',[400,401,403,422,429])
def test_native_http_rejection_keeps_status_and_reason(status):
    response=type('Response',(),{'status':status,'json':lambda self:{'message':'请先完成账号验证'}})()
    with pytest.raises(NotSubmitted,match=f'HTTP {status}.*请先完成账号验证'):
        response_receipt(response,'thread','博客','test_author')


def test_response_diagnostics_do_not_leak_data_or_treat_gateway_errors_as_rejected():
    response=type('Response',(),{'status':403,'json':lambda self:{'message':'token=secret https://example.com/?secret=yes','data':{'cookie':'private'}}})()
    with pytest.raises(NotSubmitted) as caught:response_receipt(response,'thread','博客','test_author')
    assert 'secret' not in str(caught.value) and 'private' not in str(caught.value)
    response.status=502
    with pytest.raises(RuntimeError,match='结果不明.*502'):response_receipt(response,'thread','博客','test_author')
    response.status=200;response.json=lambda:{'code':200,'data':12345678}
    assert response_receipt(response,'reply',URL,'test_author')['comment_id']=='12345678'


def test_unreadable_http_rejection_is_not_a_success():
    response=type('Response',(),{'status':403,'json':lambda self:(_ for _ in ()).throw(ValueError('HTML'))})()
    with pytest.raises(NotSubmitted,match='HTTP 403.*未返回可读原因'):
        response_receipt(response,'thread','博客','test_author')


def test_comment_guard_exact_native_form_prearm_duplicate_and_reply_target():
    payload={'kind':'reply','body':'正确评论'};data={'content':'正确评论','articleId':'123456789','commentId':''}
    g=SubmitGuard(payload,URL);r=Route(urlencode(data));g.route(r);assert r.result=='blocked' and g.count==0
    g.armed=True;a=Route(urlencode(data));b=Route(urlencode(data));g.route(a);g.route(b);assert a.result=='sent' and b.result=='blocked'
    for delta in [{'content':'不一样'},{'articleId':'98765'},{'commentId':'12345'},{'replyId':'12345'}]:
        g=SubmitGuard(payload,URL);g.armed=True;r=Route(urlencode({**data,**delta}));g.route(r);assert r.result=='blocked'
    g=SubmitGuard(payload,URL);g.armed=True;r=Route(urlencode(data)+'&content=evil');g.route(r);assert r.result=='blocked'


def test_article_guard_preserves_ai_disclosure_no_backup_and_no_existing_article_overwrite():
    p=article();g=SubmitGuard(p,'博客');data={'title':p['title'],'markdowncontent':p['body']+'\n','tags':'人工智能','status':0,'pubStatus':'publish','readType':'public','type':'original','creation_statement':1,'sync_git_code':0}
    assert g.valid(data)
    for delta in [{'sync_git_code':1},{'creation_statement':0},{'id':'12345'},{'articleId':'12345'},{'tags':'其他'},{'markdowncontent':'改变正文'},{'readType':'needvip'},{'pubStatus':'draft'},{'cover_images':['image']},{'creator_activity_id':'activity'}]:
        assert not g.valid({**data,**delta})
