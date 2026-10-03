import pytest
from concurrent.futures import ThreadPoolExecutor
from jm_workbench.web.app import create_app
from jm_workbench.community.models import CommunityAccount, CommunityPost
from jm_workbench.community.adapters import tieba_reply_receipt
from jm_workbench.community.registry import tieba_thread_url


class Fake:
    def __init__(self):self.sent=[];self.fail=None
    def check(self,*args):return 'test-tieba'
    def publish(self,a,s,p,t):
        self.sent.append((p,t))
        if self.fail:raise self.fail
        return {'post_id':'345678','url':'https://tieba.baidu.com/p/123456?pid=345678','visibility':'unverified'}


@pytest.fixture
def ctx(tmp_path):
    f=Fake();s=create_app(tmp_path,worker=False,community_adapter=f).state.community
    now=[1800000000.];s.clock=lambda:now[0]
    a=s.save_account(CommunityAccount(name='reply test',platform='tieba'));s.check_account(a['id'])
    return s,f,a['id'],now


def reply(s,aid,request='reply-test-00001',body='针对这个具体问题提供一个解决思路',url='https://tieba.baidu.com/p/123456'):
    return s.save(CommunityPost(request_id=request,kind='reply',title='回复测试标题',body=body,
       source_title='真实原帖标题',source_excerpt='原帖问题',targets=[{'account_id':aid,'destination':url}]))['id']


def test_reply_preserves_text_target_and_source(ctx):
    s,f,a,_=ctx;pid=reply(s,a);s.launch(pid);s.tick()
    assert len(f.sent)==1 and f.sent[0][0]['kind']=='reply'
    p=s.state()['posts'][0]
    assert p['payload']['source_excerpt']=='原帖问题'
    assert p['jobs'][0]['state']=='submitted'
    assert p['payload']['body']=='针对这个具体问题提供一个解决思路'


def test_same_thread_even_changed_comment_rejected(ctx):
    s,_,a,_=ctx;s.launch(reply(s,a))
    with pytest.raises(ValueError,match='重复'):
        s.launch(reply(s,a,'reply-test-00002','完全不同的另一个答复',url='https://tieba.baidu.com/p/123456?pn=2'))


def test_same_content_different_thread_rejected(ctx):
    s,_,a,_=ctx;s.launch(reply(s,a))
    with pytest.raises(ValueError,match='重复'):
        s.launch(reply(s,a,'reply-test-00002','针对 这个具体问题，提供一个解决思路！',url='https://tieba.baidu.com/p/999999'))


def test_concurrent_reply_reservation_is_unique(ctx):
    s,_,a,_=ctx;pids=[reply(s,a,'parallel-reply-'+str(i)) for i in range(4)]
    def run(pid):
        try:s.launch(pid);return True
        except ValueError:return False
    with ThreadPoolExecutor(max_workers=4) as pool:assert sum(pool.map(run,pids))==1


def test_unknown_stops_all_tieba_and_never_retries(ctx):
    s,f,a,n=ctx;f.fail=TimeoutError();s.launch(reply(s,a));s.tick();n[0]+=90000;s.tick()
    assert len(f.sent)==1 and s.state()['posts'][0]['jobs'][0]['state']=='unknown'
    assert s.state()['risk'][0]['platform']=='tieba'


def test_daily_separate_thread_and_reply_budgets(ctx):
    s,f,a,n=ctx
    from datetime import datetime
    from jm_workbench.community.service import SHANGHAI
    n[0]=datetime(2026,10,3,10,0,tzinfo=SHANGHAI).timestamp();s.check_account(a)
    for i in range(6):
        pid=reply(s,a,'reply-budget-'+str(i),body='不同评论内容'+str(i),url='https://tieba.baidu.com/p/'+str(123456+i))
        s.launch(pid);s.tick();n[0]+=1801
    assert len(f.sent)==5
    waiting=s.state()['posts'][0]['jobs'][0]
    assert waiting['state']=='queued'
    assert datetime.fromtimestamp(waiting['due'],SHANGHAI).day==4


def test_other_platform_reply_is_rejected(ctx):
    s,_,_,_=ctx
    a=s.save_account(CommunityAccount(name='web only',platform='zhihu'))
    pid=reply(s,a['id'])
    with pytest.raises(ValueError,match='仅百度贴吧'):s.launch(pid)


@pytest.mark.parametrize('url',['http://tieba.baidu.com/p/123456','https://tieba.baidu.com.evil/p/123456','https://tieba.baidu.com/f?kw=x','https://x@tieba.baidu.com/p/123456'])
def test_invalid_reply_target(url):
    with pytest.raises(ValueError):tieba_thread_url(url)


def test_reply_receipt_requires_comment_id_not_thread_id():
    from jm_workbench.community.adapters import NotSubmitted
    assert tieba_reply_receipt({'errno':0,'data':{'pid':'345678'}},'https://tieba.baidu.com/p/123456')['comment_id']=='345678'
    assert tieba_reply_receipt({'errno':0,'post':{'id':'345678'}},'https://tieba.baidu.com/p/123456')['post_id']=='345678'
    with pytest.raises(RuntimeError):tieba_reply_receipt({'errno':0,'data':{'tid':'123456'}},'https://tieba.baidu.com/p/123456')
    with pytest.raises(NotSubmitted):tieba_reply_receipt({'errno':4},'https://tieba.baidu.com/p/123456')
