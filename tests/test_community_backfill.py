import json
from datetime import datetime
import pytest
from test_community_daily import setup_plan, config
from test_community_replies import ctx
from jm_workbench.community.service import SHANGHAI
from jm_workbench.community.models import DailyPlan


def test_register_all_missing_days_without_sending_or_backdating(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx,topics=3,replies=10)
    s.daily.control(p,'pause');n[0]+=2*86400
    # Evidence that the plan started; registration does not fabricate day execution.
    with s.store.connect(True) as db:db.execute("INSERT INTO community_plan_days VALUES(?,?,'waiting','offline',?,?)",(p,'2026-10-03',n[0]-2*86400,n[0]-2*86400))
    result=s.backfill.register([p],'2026-10-04')
    assert result['created']==12 and not f.sent
    assert result['backfill']['with_content']==12
    assert len(s.state()['posts'])==12 and not s.store.rows('SELECT * FROM community_jobs')
    assert all(r['created']==n[0] for r in s.state()['posts'])
    again=s.backfill.register([p],'2026-10-04')
    assert again['created']==0 and len(s.state()['posts'])==12
    assert s.daily.get(p)['state']=='paused'


def test_existing_unsent_jobs_reused_and_receipts_never_rewritten(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx);s.daily.prepare(p);s.tick();s.daily.control(p,'pause')
    before=s.store.rows('SELECT id,receipt,snapshot,state FROM community_jobs ORDER BY id')
    n[0]+=86400
    result=s.backfill.register([p],'2026-10-03')
    assert result['created']==5
    assert len(s.state()['posts'])==6
    assert s.store.rows('SELECT id,receipt,snapshot,state FROM community_jobs ORDER BY id')==before
    assert all(r['status']=='needs_check' for r in result['backfill']['items'])


def test_shortage_is_an_obligation_not_a_fake_comment(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx,topics=1,replies=0);s.daily.prepare(p);s.daily.control(p,'pause');n[0]+=86400
    r=s.backfill.register([p],'2026-10-03')['backfill']
    assert r['replies']==5 and sum(i['status']=='missing_target' for i in r['items'])==5
    assert len(s.state()['posts'])==1 and not f.sent


def test_no_today_or_future_or_never_started_plan(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx)
    with pytest.raises(ValueError,match='昨天'):s.backfill.register([p],'2026-10-03')
    n[0]+=86400
    with pytest.raises(ValueError,match='尚未开始'):s.backfill.register([p],'2026-10-03')
    assert not s.backfill.state()['items']


def test_reply_zero_setting_does_not_hide_explicit_user_backfill_goal(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx);s.daily.control(p,'pause');d=config(a).model_dump();d['replies_per_day']=0
    s.daily.save(DailyPlan(**d),p);s.daily.control(p,'enable');s.daily.prepare(p);s.daily.control(p,'pause');n[0]+=86400
    r=s.backfill.register([p],'2026-10-03',5)['backfill']
    assert r['replies']==5
    assert s.daily.get(p)['payload']['replies_per_day']==0


def test_failed_readonly_connection_cannot_start_jobs(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx);s.daily.prepare(p);s.daily.control(p,'pause');n[0]+=86400
    s.backfill.register([p],'2026-10-03')
    before=s.store.rows('SELECT * FROM community_jobs')
    def fail(*args):raise ValueError('connection unavailable')
    f.check=fail
    with pytest.raises(ValueError,match='账号检查未完成'):s.backfill.prepare(p)
    assert s.store.rows('SELECT * FROM community_jobs')==before and not f.sent


def test_recorded_manual_article_is_not_duplicated(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx);s.daily.prepare(p);s.daily.control(p,'pause')
    with s.store.connect(True) as db:
        row=db.execute("SELECT j.id,j.post_id FROM community_jobs j WHERE json_extract(snapshot,'$.payload.kind')='thread'").fetchone()
        db.execute('DELETE FROM community_plan_items WHERE post_id=?',(row['post_id'],))
        db.execute("UPDATE community_jobs SET state='recorded',updated=? WHERE id=?",(n[0],row['id']))
    n[0]+=86400
    r=s.backfill.register([p],'2026-10-03')['backfill']
    assert r['threads']==0 and r['replies']==5


def test_daily_plan_does_not_reuse_backfill_reserved_content(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx,topics=3,replies=10)
    s.daily.prepare(p);s.daily.control(p,'pause');n[0]+=2*86400
    s.backfill.register([p],'2026-10-04')
    reserved={json.loads(r['payload'])['body'] for r in s.store.rows('SELECT p.payload FROM community_posts p JOIN community_backfill b ON b.post_id=p.id')}
    s.check_account(a);s.daily.control(p,'enable');s.daily.prepare(p)
    today=s.store.rows("SELECT p.payload FROM community_posts p JOIN community_plan_items i ON i.post_id=p.id WHERE i.day='2026-10-05'")
    assert today and all(json.loads(r['payload'])['body'] not in reserved for r in today)


def test_registered_historical_queue_is_not_expired_at_next_daily_start(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx);s.daily.prepare(p);n[0]+=86400
    s.backfill.register([p],'2026-10-03');s.daily.tick()
    jobs=s.store.rows("SELECT j.state FROM community_jobs j JOIN community_backfill b ON b.post_id=j.post_id")
    assert len(jobs)==6 and all(r['state']=='queued' for r in jobs)


def test_repeated_concurrent_registration_has_one_slot_and_one_draft(ctx):
    from concurrent.futures import ThreadPoolExecutor
    s,f,a,n=ctx;p=setup_plan(ctx);s.daily.prepare(p);s.daily.control(p,'pause');n[0]+=2*86400
    with ThreadPoolExecutor(max_workers=2) as pool:
        values=list(pool.map(lambda _:s.backfill.register([p],'2026-10-04'),range(2)))
    assert sum(r['created'] for r in values)==12
    assert s.backfill.state()['total']==12 and len(s.state()['posts'])==12
    assert not f.sent
