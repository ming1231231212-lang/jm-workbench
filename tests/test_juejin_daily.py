import json
from datetime import datetime
import pytest
from jm_workbench.web.app import create_app
from jm_workbench.community.models import CommunityAccount, CommunityPost, DailyPlan
from jm_workbench.community.registry import juejin_thread_url, tag_label
from jm_workbench.community.service import SHANGHAI
from jm_workbench.community.juejin import SubmitGuard, receipt, validate_payload
from jm_workbench.community.adapters import NotSubmitted


class Fake:
    def __init__(self): self.sent = []; self.fail = None
    def check(self, a, secret): return '123456789012345'
    def publish(self, a, secret, payload, target):
        self.sent.append((a['platform'], payload, target))
        if self.fail: raise self.fail
        return {'post_id': '1234567890123456', 'url': 'https://juejin.cn/post/1234567890123456' if a['platform'] == 'juejin' else 'https://tieba.baidu.com/p/123456'}
    def discover(self, *args): return []


@pytest.fixture
def setup(tmp_path):
    f = Fake(); s = create_app(tmp_path, worker=False, community_adapter=f).state.community
    clock = [datetime(2026,10,4,10,tzinfo=SHANGHAI).timestamp()]; s.clock = lambda: clock[0]
    a = s.save_account(CommunityAccount(name='掘金测试', platform='juejin'))['id']; s.check_account(a)
    return s, f, a, clock


def article(i=0):
    return {'title':'如何验证资源是否适合任务'+str(i), 'body':'本文使用AI辅助整理。'+('使用演示数据核对输入、输出与依赖，未知的内容不补写。' * 10)+str(i), 'platform_tags':['人工智能']}


def plan(a, topics=2, replies=7):
    return DailyPlan(name='掘金每日',account_id=a,board='人工智能',rules_note='相关技术分享和讨论，不带营销外链或联系方式。',
        topics=[article(i) for i in range(topics)],replies=[{'url':f'https://juejin.cn/post/{1234567890123400+i}',
        'title':'原帖标题'+str(i),'excerpt':'这是一段原文，需要核对目标问题内容。','body':'AI辅助整理：对照这个问题，建议分别核对依赖和输出，保留原始输入以便检查。'+str(i)} for i in range(replies)])


def launch(s,a,i=0,kind='thread',body=None,target=None):
    data=article(i) if kind=='thread' else {'title':'评论测试标题','body':body or 'AI辅助整理：对照原文中的问题，建议保留失败样本，再逐步检查依赖及输出。'+str(i)}
    if body is not None:data['body']=body
    p=s.save(CommunityPost(request_id=f'juejin-test-{kind}-{i}',kind=kind,**data,
        targets=[{'account_id':a,'destination':target or ('人工智能' if kind=='thread' else f'https://juejin.cn/post/{1234567890123400+i}')}]))['id']
    s.launch(p);return p


def test_prepare_uses_juejin_tags_and_unique_targets(setup):
    s,f,a,n=setup;p=s.daily.save(plan(a))['id'];s.daily.control(p,'enable');s.daily.prepare(p);s.daily.prepare(p,True)
    posts=s.state()['posts'];assert len(posts)==6 and not f.sent
    topic=next(p for p in posts if p['payload']['kind']=='thread')
    assert topic['payload']['platform_tags']==['人工智能'] and topic['payload']['category']=='人工智能'
    assert len({p['payload']['targets'][0]['destination'] for p in posts if p['payload']['kind']=='reply'})==5


def test_recorded_web_article_consumes_today_budget_and_no_extra_daily_article(setup):
    s,f,a,n=setup;p=launch(s,a)
    with s.store.connect(True) as db:db.execute("UPDATE community_jobs SET state='recorded',started=0,updated=?",(n[0],))
    ident=s.daily.save(plan(a))['id'];s.daily.control(ident,'enable');s.daily.prepare(ident)
    assert len(s.state()['posts'])==6 and '今日文章额度已用' in s.daily.get(ident)['message']
    assert sum(x['payload']['kind']=='thread' for x in s.state()['posts'])==1
    s.tick();assert not f.sent  # The registered article also occupies the spacing budget.


def test_six_attempts_shared_by_account_aliases_and_separate_daily_limits(setup):
    s,f,a,n=setup;launch(s,a);s.tick()
    a2=s.save_account(CommunityAccount(name='同身份别名',platform='juejin'))['id'];s.check_account(a2)
    for i in range(6):
        n[0]+=1801;launch(s,a2,i,kind='reply');s.tick()
    assert len(f.sent)==6 and sum(x[1]['kind']=='reply' for x in f.sent)==5
    assert any(j['state']=='queued' for p in s.state()['posts'] for j in p['jobs'])


def test_same_content_and_same_target_are_independently_blocked(setup):
    s,_,a,_=setup;launch(s,a,kind='reply')
    with pytest.raises(ValueError,match='重复'):launch(s,a,1,kind='reply',target='https://juejin.cn/post/1234567890123400?x=1')
    with pytest.raises(ValueError,match='重复'):launch(s,a,2,kind='reply',body='AI辅助整理：对照原文中的问题，建议保留失败样本，再逐步检查依赖及输出。0')


def test_platform_failure_does_not_pause_other_platform_plan(setup):
    s,f,a,n=setup
    ja=s.daily.save(plan(a,replies=0))['id'];s.daily.control(ja,'enable')
    ta=s.save_account(CommunityAccount(name='贴吧',platform='tieba'))['id'];s.check_account(ta)
    tp=s.daily.save(DailyPlan(name='贴吧每日',account_id=ta,board='ai工具',rules_note='发布与板块相关的原创内容及有帮助的回复'))['id'];s.daily.control(tp,'enable')
    f.fail=TimeoutError();s.tick();n[0]+=86400;s.tick()
    assert len(f.sent)==1 and s.daily.get(ja)['state']=='paused'
    assert s.daily.get(tp)['state']=='enabled'


def test_discovery_wrong_platform_rejected_without_send(setup):
    s,f,a,n=setup
    d=plan(a,topics=0,replies=0).model_dump();d['source_boards']=['人工智能']
    d['reply_rules']=[{'name':'Skill检查','terms':['Skill','输出'],'body':'AI辅助整理：建议先保留同一份最小输入，再核对输出约束及依赖，记录实际失败的位置。','require_question':False}]
    f.discover=lambda *args:[{'url':'https://tieba.baidu.com/p/123456','title':'Skill输出','excerpt':'Skill的输出如何检查，这是原文内容。'}]
    p=s.daily.save(DailyPlan(**d))['id'];s.daily.control(p,'enable');s.daily.prepare(p)
    assert s.daily.get(p)['state']=='paused' and not f.sent


def test_historical_web_claim_is_bound_without_changing_snapshot(setup):
    s,f,a,n=setup;p=launch(s,a);old=s.job(s.jobs(p)[0]['id'])
    with s.store.connect(True) as db:
        db.execute("UPDATE community_claims SET identity=?",('manual:'+a,))
    s.check_account(a)
    assert s.store.rows('SELECT 1 FROM community_claims WHERE identity=?',('123456789012345',))
    assert s.job(old['id'])['snapshot']==old['snapshot']


@pytest.mark.parametrize('url',['http://juejin.cn/post/1234567890123','https://juejin.cn.evil/post/1234567890123','https://u@juejin.cn/post/1234567890123','https://juejin.cn/editor/drafts/1234567890123'])
def test_invalid_article_url(url):
    with pytest.raises(ValueError):juejin_thread_url(url)


def test_payload_requires_disclosure_and_relevant_tag():
    data=article();validate_payload(data,'人工智能')
    with pytest.raises(ValueError):validate_payload({**data,'platform_tags':[]},'人工智能')
    with pytest.raises(ValueError):validate_payload({**data,'body':data['body'].replace('AI辅助','原创')},'人工智能')
    with pytest.raises(ValueError):validate_payload({**data,'body':data['body']+' https://example.com'},'人工智能')
    with pytest.raises(ValueError):tag_label('../tag/AI')


def test_reply_receipt_requires_comment_id_and_matching_article():
    target='https://juejin.cn/post/1234567890123456'
    r=receipt({'err_no':0,'data':{'comment_info':{'comment_id':'2345678901234567','item_id':'1234567890123456'}}},'reply',target)
    assert r['comment_id']=='2345678901234567' and r['visibility']=='unverified'
    with pytest.raises(RuntimeError):receipt({'err_no':0,'data':{'item_id':'1234567890123456'}},'reply',target)
    with pytest.raises(NotSubmitted):receipt({'err_no':1},'reply',target)
    with pytest.raises(RuntimeError):receipt({'data':{'comment_id':'2345678901234567'}},'reply',target)


def test_request_guard_blocks_duplicates_wrong_target_and_nested_reply():
    class Route:
        def __init__(self,data):self.request=type('Req',(),{'method':'POST','post_data':json.dumps(data)})();self.result=''
        def fallback(self):self.result='sent'
        def abort(self,*args):self.result='blocked'
    guard=SubmitGuard('reply',{'body':'正确正文'},'https://juejin.cn/post/1234567890123456')
    data={'item_id':'1234567890123456','item_type':2,'comment_content':'正确正文','comment_pics':[]}
    a=Route(data);b=Route(data);guard.route(a);guard.route(b)
    assert a.result=='sent' and b.result=='blocked'
    for mutation in [{'item_id':'wrong'},{'reply_id':'123'},{'comment_content':'不同正文'},{'comment_pics':['image']}]:
        g=SubmitGuard('reply',{'body':'正确正文'},'https://juejin.cn/post/1234567890123456');r=Route({**data,**mutation});g.route(r);assert r.result=='blocked'


def test_article_guard_only_permits_expected_autosaved_draft():
    g=SubmitGuard('thread',article(),'人工智能','1234567890123456')
    assert g.valid({'draft_id':'1234567890123456'})
    assert not g.valid({'draft_id':'different'})
