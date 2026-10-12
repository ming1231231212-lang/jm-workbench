import json
import pytest
from test_community_replies import ctx
from test_community_daily import setup_plan


def history(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx,topics=1,replies=5)
    s.daily.prepare(p);s.daily.control(p,'pause');n[0]+=86400
    s.backfill.register([p],'2026-10-03');s.daily.control(p,'enable')
    return s,f,a,n,p


def test_explicit_queue_preserves_old_snapshots_and_is_idempotent(ctx):
    s,f,a,n,p=history(ctx)
    with s.store.connect(True) as db:
        rows=db.execute('SELECT id,snapshot FROM community_jobs').fetchall()
        for r in rows:
            snap=json.loads(r['snapshot']);snap['revision']='old-version'
            db.execute('UPDATE community_jobs SET snapshot=? WHERE id=?',(json.dumps(snap),r['id']))
    before=s.store.rows('SELECT id,snapshot,receipt FROM community_jobs ORDER BY id')
    assert s.backfill.queue(p)['queued']==6 and not f.sent
    assert s.backfill.queue(p)['queued']==0
    old=s.store.rows("SELECT id,snapshot,receipt FROM community_jobs WHERE state='cancelled' ORDER BY id")
    assert old==before
    assert len(s.store.rows('SELECT * FROM community_backfill_continuations'))==6
    assert all(r['status']=='queued' for r in s.backfill.state()['items'])
    assert len(s.backfill.preview([p],'2026-10-03'))==6
    s.tick();assert len(f.sent)==1
    assert s.backfill.state()['submitted']==1
    assert len(s.backfill.preview([p],'2026-10-03'))==5


@pytest.mark.parametrize('state,receipt,started',[
    ('unknown','{}',1),('submitted','{}',1),('failed','{}',0),
    ('paused','{}',1),('cancelled','{}',0),
    ('failed','{"post_id":"123"}',0),
])
def test_unsafe_or_cancelled_attempt_never_replays(ctx,state,receipt,started):
    s,f,a,n,p=history(ctx)
    with s.store.connect(True) as db:
        db.execute('UPDATE community_jobs SET state=?,receipt=?,started=?',(state,receipt,started))
    before=s.store.rows('SELECT * FROM community_jobs ORDER BY id')
    assert s.backfill.queue(p)['queued']==0
    assert s.store.rows('SELECT * FROM community_jobs ORDER BY id')==before and not f.sent


def test_queue_accepts_proven_preflight_failure_but_not_changed_identity(ctx):
    s,f,a,n,p=history(ctx)
    with s.store.connect(True) as db:
        db.execute("UPDATE community_jobs SET state='failed',receipt=?",('{"phase":"preflight","submitted":false}',))
    old_check=f.check;f.check=lambda *args:'changed'
    with pytest.raises(ValueError):s.backfill.queue(p)
    assert len(s.store.rows('SELECT * FROM community_jobs'))==6
    f.check=old_check
    assert s.backfill.queue(p)['queued']==6


def test_risk_and_pause_block_backfill_and_stop_after_queue(ctx):
    s,f,a,n,p=history(ctx)
    with s.store.connect(True) as db:db.execute("INSERT INTO community_risk VALUES('tieba','risk',0)")
    with pytest.raises(ValueError,match='限制'):s.backfill.queue(p)
    with s.store.connect(True) as db:db.execute('DELETE FROM community_risk')
    s.daily.control(p,'pause')
    with pytest.raises(ValueError,match='启用'):s.backfill.queue(p)
    s.daily.control(p,'enable');s.backfill.queue(p);s.daily.control(p,'pause');s.tick()
    assert not f.sent
    assert not s.store.rows("SELECT * FROM community_jobs WHERE state='queued'")


def test_existing_and_backfill_share_real_daily_budget(ctx):
    s,f,a,n,p=history(ctx);s.backfill.queue(p)
    for _ in range(6):s.tick();n[0]+=1801
    assert len(f.sent)==6
    assert sum(x[0]['kind']=='thread' for x in f.sent)==1
    assert s.backfill.state()['submitted']==6


def test_daily_preparation_prioritizes_backfill_without_new_jobs(ctx):
    s,f,a,n,p=history(ctx);s.backfill.queue(p)
    before=s.store.rows('SELECT id FROM community_jobs ORDER BY id')
    assert '优先执行历史补发' in s.daily.prepare(p)['message']
    assert s.store.rows('SELECT id FROM community_jobs ORDER BY id')==before
    assert s.daily.state()[0]['days'][0]['counts']['thread']['submitted']==0


def test_comment_terms_scattered_across_article_do_not_match():
    from jm_workbench.community.daily import eligible
    rule={'terms':['API','错误'],'require_question':False}
    assert not eligible(rule,{'title':'AI框架对比','excerpt':'本文首先介绍 API 设计。另一个完全不同的话题是团队沟通错误。'})
    assert eligible(rule,{'title':'API错误分类','excerpt':'讨论参数错误、授权失败和服务异常如何区分。'})
