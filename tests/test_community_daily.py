import json
import pytest
from datetime import datetime,timedelta
from jm_workbench.community.models import DailyPlan,ReplyRule
from jm_workbench.community.service import SHANGHAI
from test_community_replies import ctx


def config(a,topics=3,replies=10):
    return DailyPlan(name='日常试用',account_id=a,board='ai工具',rules_note='发布原创工具使用方法，推广仅在指定入口',hour=10,
        topics=[{'title':'不同主题的测试帖子'+str(i),'body':'足够长的原创测试正文，用于验证每日只选择一份素材。主题'+str(i)} for i in range(topics)],
        replies=[{'url':'https://tieba.baidu.com/p/'+str(123456+i),'title':'原帖'+str(i),'excerpt':'原帖真实的问题描述，不是搜索标签。'+str(i),'body':'针对原帖提供有实际帮助的评论建议，每条内容独立。答复'+str(i)} for i in range(replies)])


def setup_plan(ctx,**opts):
    s,f,a,n=ctx;n[0]=datetime(2026,10,3,10,0,tzinfo=SHANGHAI).timestamp();s.check_account(a)
    p=s.daily.save(config(a,**opts))['id'];s.daily.control(p,'enable');return p


def test_save_is_not_start_and_account_reference_protected(ctx):
    s,f,a,n=ctx;p=s.daily.save(config(a))['id'];s.tick()
    assert not f.sent and not s.state()['posts']
    with pytest.raises(ValueError,match='每日计划'):s.delete_account(a,s.account(a)['version'])


def test_daily_one_post_five_distinct_replies_only_once(ctx):
    p=setup_plan(ctx);s,f,a,n=ctx
    s.daily.prepare(p);s.daily.prepare(p,force=True)
    posts=s.state()['posts'];assert len(posts)==6
    assert sum(x['payload']['kind']=='reply' for x in posts)==5
    assert not f.sent
    targets=[x['payload']['targets'][0]['destination'] for x in posts if x['payload']['kind']=='reply']
    assert len(set(targets))==5


def test_next_day_uses_new_material_and_never_catches_up(ctx):
    p=setup_plan(ctx);s,f,a,n=ctx;s.daily.prepare(p);old={p['id'] for p in s.state()['posts']}
    n[0]+=3*86400;s.daily.tick()
    state=s.state();assert len(state['posts'])==12 and len(state['plans'][0]['days'])==2
    assert all(j['state']=='cancelled' for p in state['posts'] if p['id'] in old for j in p['jobs'])
    bodies=[p['payload']['body'] for p in state['posts']];assert len(set(bodies))==12


def test_evening_test_is_not_cancelled_halfway_at_midnight(ctx):
    p=setup_plan(ctx);s,_,_,n=ctx
    n[0]=datetime(2026,10,3,22,0,tzinfo=SHANGHAI).timestamp();s.daily.prepare(p,force=True)
    n[0]=datetime(2026,10,4,0,1,tzinfo=SHANGHAI).timestamp();s.daily.tick()
    assert all(j['state']=='queued' for r in s.state()['posts'] for j in r['jobs'])
    assert len(s.state()['posts'])==6


def test_waits_until_shanghai_time_and_shortages_are_visible(ctx):
    p=setup_plan(ctx,topics=0,replies=1);s,_,_,n=ctx;n[0]-=60;s.daily.tick()
    assert not s.state()['posts']
    n[0]+=60;s.daily.tick();plan=s.state()['plans'][0]
    assert '帖子 0/1、评论 1/5' in plan['message'] and '不足' in plan['message']


def test_pause_keeps_history_and_does_not_resend_on_enable(ctx):
    p=setup_plan(ctx);s,f,_,_=ctx;s.daily.prepare(p);s.daily.control(p,'pause');s.tick()
    assert not f.sent and all(j['state']=='paused' for r in s.state()['posts'] for j in r['jobs'])
    s.daily.control(p,'enable');s.daily.prepare(p,force=True);s.tick();assert not f.sent


def test_platform_failure_stops_the_daily_plan(ctx):
    p=setup_plan(ctx);s,f,_,_=ctx;f.fail=TimeoutError();s.tick();s.tick()
    assert len(f.sent)==1 and s.daily.get(p)['state']=='paused'
    assert sum(j['state']=='unknown' for r in s.state()['posts'] for j in r['jobs'])==1


def test_revision_change_stops_daily_generation(ctx):
    p=setup_plan(ctx);s,_,_,_=ctx;s.cfg.code_revision='changed';s.daily.prepare(p)
    assert s.daily.get(p)['state']=='paused' and not s.state()['posts']


def test_crash_during_preparation_does_not_start_partial_jobs(ctx):
    p=setup_plan(ctx);s,f,_,_=ctx;s.daily.prepare(p)
    with s.store.connect(True) as db:db.execute("UPDATE community_plan_days SET state='preparing'")
    s.recover();s.tick();assert not f.sent and s.daily.get(p)['state']=='paused'
    assert s.state()['plans'][0]['days'][0]['state']=='error'


def test_duplicate_material_is_rolled_back_without_orphan_draft(ctx):
    p=setup_plan(ctx,topics=0,replies=1);s,_,a,n=ctx;s.daily.prepare(p);s.daily.control(p,'pause')
    changed=config(a,topics=0,replies=1).model_dump();changed['replies'][0]['url']='https://tieba.baidu.com/p/999999'
    s.daily.save(DailyPlan(**changed),p);s.daily.control(p,'enable');n[0]+=86400;s.daily.tick()
    assert len(s.state()['posts'])==1


def test_discovery_requires_relevant_original_context(ctx):
    s,f,a,n=ctx;n[0]=datetime(2026,10,3,10,0,tzinfo=SHANGHAI).timestamp()
    d=config(a,topics=0,replies=0).model_dump();d['source_boards']=['人工智能']
    d['reply_rules']=[{'name':'Skill步骤','terms':['skill','使用'],'body':'先检查适用的软件与版本，再核对说明中的输入和输出，最后用一个最小任务检查具体卡在哪一步。','require_question':True}]
    f.discover=lambda *args:[{'url':'https://tieba.baidu.com/p/123456','title':'Skill怎么使用？','excerpt':'刚找到一个skill，不清楚如何使用，具体应该从哪里开始？','author_id':'other'},
                            {'url':'https://tieba.baidu.com/p/123457','title':'Skill怎么使用？','excerpt':'网盘付费课程，请购买下载，这是广告，应该被排除','author_id':'other'}]
    p=s.daily.save(DailyPlan(**d))['id'];s.daily.control(p,'enable');s.daily.prepare(p)
    posts=s.state()['posts'];assert len(posts)==1 and posts[0]['payload']['source_title']=='Skill怎么使用？'
    assert posts[0]['payload']['targets'][0]['destination'].endswith('/123456')


def test_ordinary_auto_reply_rule_cannot_inject_promotional_link():
    with pytest.raises(ValueError):ReplyRule(name='promote',terms=['AI'],body='请访问我这个平台了解所有功能，可以在这里得到帮助 https://example.com',require_question=False)
