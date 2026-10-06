import json
import pytest
from test_community_daily import setup_plan, config
from test_community_replies import ctx
from jm_workbench.community.models import DailyPlan
from jm_workbench.community.adapters import NotSubmitted


def test_article_only_plan_does_not_discover_or_queue_replies(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx);s.daily.control(p,'pause')
    d=config(a).model_dump();d['replies_per_day']=0
    s.daily.save(DailyPlan(**d),p);s.daily.control(p,'enable');s.daily.prepare(p)
    assert len(s.state()['posts'])==1
    assert s.state()['plans'][0]['days'][0]['reply_goal']==0


def test_shortage_rechecks_and_fills_only_missing_slots(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx,topics=1,replies=0)
    d=config(a,topics=1,replies=0).model_dump()
    d['source_boards']=['人工智能']
    d['reply_rules']=[dict(name='Skill',terms=['skill'],body='先核对当前工具与版本，然后用最小示例复现问题，检查输入输出和错误信息，可以更快定位具体失败步骤。',require_question=True)]
    s.daily.control(p,'pause');s.daily.save(DailyPlan(**d),p);s.daily.control(p,'enable')
    calls=[];found=[]
    f.discover=lambda *args:(calls.append(n[0]) or found)
    s.daily.prepare(p);assert len(s.state()['posts'])==1
    s.daily.prepare(p);assert len(calls)==1
    found.append(dict(url='https://tieba.baidu.com/p/123456',title='Skill怎么用',excerpt='我在使用Skill时无法开始，请教怎么查找错误和定位原因？',author_id='someone'))
    n[0]+=1800;s.daily.prepare(p)
    assert len(s.state()['posts'])==2
    n[0]+=1800;s.daily.prepare(p,force=True)
    assert len(s.state()['posts'])==2


def test_prepare_connection_failure_is_durable_wait_and_recovers(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx);original=f.check
    f.check=lambda *args:(_ for _ in ()).throw(TimeoutError())
    s.daily.prepare(p)
    assert s.daily.get(p)['state']=='enabled' and not s.state()['posts']
    d=s.state()['plans'][0]['days'][0]
    assert d['state']=='waiting' and d['next_check']>n[0]
    f.check=original;n[0]=d['next_check'];s.daily.prepare(p)
    assert len(s.state()['posts'])==6


def test_manual_stop_during_wait_survives_restart(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx)
    f.check=lambda *args:(_ for _ in ()).throw(TimeoutError())
    s.daily.prepare(p);s.daily.control(p,'pause');s.recover();n[0]+=90000;s.tick()
    assert s.daily.get(p)['state']=='paused' and not f.sent and not s.state()['posts']


def test_identity_change_never_auto_recovers(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx);f.check=lambda *args:'another-user'
    s.daily.prepare(p);n[0]+=3600;s.tick()
    assert s.daily.get(p)['state']=='paused' and not f.sent


def test_safe_account_preflight_retries_same_job_without_budget(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx);s.daily.prepare(p);original=f.check
    f.check=lambda *args:(_ for _ in ()).throw(TimeoutError())
    s.tick()
    jobs=s.store.rows('SELECT * FROM community_jobs')
    retry=next(j for j in jobs if json.loads(j['receipt']).get('retry_attempt'))
    assert retry['state']=='queued' and retry['started']==0 and retry['due']>n[0]
    assert s.daily.get(p)['state']=='enabled' and not s.state()['risk']
    # Every queue item is prevented from tight-looping on the same account fault.
    assert all(j['due']>=retry['due'] for j in jobs)
    f.check=original;n[0]=retry['due'];s.tick()
    assert len(f.sent)==1 and len(s.state()['posts'])==6


def test_stop_requested_during_failed_preflight_wins(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx);s.daily.prepare(p)
    def check(*args):
        s.stop_all()
        raise TimeoutError()
    f.check=check;s.tick();n[0]+=3600;s.tick()
    assert not f.sent and all(j['state']=='paused' for r in s.state()['posts'] for j in r['jobs'])


def test_platform_rejection_still_stops_without_retry(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx);f.fail=NotSubmitted('平台拒绝发布')
    s.tick();n[0]+=3600;s.tick()
    assert len(f.sent)==1 and s.state()['risk'] and s.daily.get(p)['state']=='paused'


def test_restart_partial_materialization_completes_without_duplicates(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx);s.daily.prepare(p)
    with s.store.connect(True) as db:
        db.execute("UPDATE community_plan_days SET state='preparing'")
    s.recover();s.daily.prepare(p)
    assert s.daily.get(p)['state']=='enabled' and len(s.state()['posts'])==6


def test_recovery_of_running_write_is_still_unknown(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx);s.daily.prepare(p)
    with s.store.connect(True) as db:
        db.execute("UPDATE community_jobs SET state='running' WHERE id=(SELECT id FROM community_jobs LIMIT 1)")
        db.execute("UPDATE community_plan_days SET state='preparing'")
    s.recover();s.tick()
    assert s.daily.get(p)['state']=='paused' and not f.sent and s.state()['risk']


def test_paused_plan_has_no_next_auto_action(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx);s.daily.prepare(p);s.daily.control(p,'pause')
    assert s.state()['plans'][0]['next_action_at']==0


def test_budget_wait_has_actual_next_time(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx);s.tick();s.tick()
    queued=[j for r in s.state()['posts'] for j in r['jobs'] if j['state']=='queued']
    assert any('北京时间' in j['message'] for j in queued)
    plan=s.state()['plans'][0]
    assert plan['next_action_at']>=n[0]+1800


def test_browser_restore_reuses_exact_profile_and_never_reopens_connected(monkeypatch,tmp_path):
    from jm_workbench.community import adapters
    from jm_workbench.adapters.errors import LocalBrowserError
    from types import SimpleNamespace
    adapter=adapters.CommunityAdapter(SimpleNamespace(values={}))
    a={'platform':'tieba','profile_dir':str(tmp_path/'bound-profile')}
    calls=[];opened=[]
    def endpoint(profile):
        calls.append(profile)
        if len(calls)==1:raise LocalBrowserError('offline')
        return 'ws://127.0.0.1:12345/devtools/browser/test'
    monkeypatch.setattr(adapters,'endpoint',endpoint)
    monkeypatch.setattr(adapters.time,'sleep',lambda _:None)
    monkeypatch.setattr(adapter,'open',lambda account,url:opened.append((account['profile_dir'],url)))
    adapter.ensure_connection(a);adapter.ensure_connection(a)
    assert opened==[(a['profile_dir'],'https://tieba.baidu.com/')]
    assert all(p==a['profile_dir'] for p in calls)


def test_preflight_backoff_persists_across_restart_without_early_send(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx);s.daily.prepare(p);check=f.check
    f.check=lambda *args:(_ for _ in ()).throw(TimeoutError())
    s.tick();due=min(j['due'] for r in s.state()['posts'] for j in r['jobs'])
    s.recover();f.check=check;n[0]=due-1;s.tick();assert not f.sent
    n[0]=due;s.tick();assert len(f.sent)==1


def test_matching_question_cannot_borrow_keywords_from_unrelated_paragraph():
    from jm_workbench.community.daily import eligible
    rule=dict(terms=['资料','整理'],require_question=True)
    assert not eligible(rule,dict(title='AI会影响社会结构吗？',excerpt='人工智能影响就业。人们平时会做资料整理。技术改变社会结构，但是长期变化尚未确定。'))
    assert eligible(rule,dict(title='如何用AI整理资料？',excerpt='我有一批资料需要整理成笔记，想知道如何拆分和处理，应该先做什么？'))


def test_source_fairness_bounds_total_and_deduplicates_cross_board():
    from jm_workbench.community.adapters import fair_candidates
    sources=[['a'+str(i) for i in range(20)],['b'+str(i) for i in range(20)],['c'+str(i) for i in range(20)]]
    result=fair_candidates(sources)
    assert len(result)==18 and all(sum(x.startswith(prefix) for x in result)==6 for prefix in 'abc')
    assert fair_candidates([['same','a'],['same','b']])==['same','a','b']
