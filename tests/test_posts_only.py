import json
from datetime import datetime
from jm_workbench.community.models import DailyPlan
from jm_workbench.community.service import SHANGHAI
from test_community_daily import setup_plan
from test_community_replies import ctx
from test_auto_materials import supply


def switch(s, p):
    s.daily.control(p, 'pause')
    payload = s.daily.get(p)['payload']
    payload.update(replies_per_day=0, hour=1, minute=0)
    s.daily.save(DailyPlan(**payload), p)
    return payload


def test_switch_cancels_unsent_comments_but_preserves_article_and_receipts(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx);s.daily.prepare(p)
    jobs=s.store.rows('SELECT * FROM community_jobs')
    reply=next(j for j in jobs if json.loads(j['snapshot'])['payload']['kind']=='reply')
    with s.store.connect(True) as db:
        db.execute("UPDATE community_jobs SET state='recorded',receipt=? WHERE id=?", ('{"url":"https://tieba.baidu.com/p/123456"}',reply['id']))
    preserved=s.job(reply['id'])
    switch(s,p)
    assert s.job(reply['id'])==preserved
    current=s.store.rows('SELECT * FROM community_jobs')
    assert sum(j['state']=='cancelled' for j in current)==4
    assert next(j for j in current if json.loads(j['snapshot'])['payload']['kind']=='thread')['state']=='paused'
    day=s.daily.state()[0]['days'][0]
    assert day['reply_goal']==0 and day['counts']['reply']['recorded']==1
    assert '自动评论已关闭' in day['message']
    s.daily.control(p,'enable');s.daily.prepare(p,force=True)
    assert len(s.state()['posts'])==6 and not f.sent


def test_posts_only_skips_registered_comment_backfill(ctx):
    s,f,a,n=ctx;p=setup_plan(ctx);s.daily.prepare(p);s.daily.control(p,'pause');n[0]+=86400
    s.backfill.register([p],'2026-10-03')
    switch(s,p);s.daily.control(p,'enable')
    before=[j for j in s.store.rows('SELECT * FROM community_jobs') if json.loads(j['snapshot'])['payload']['kind']=='reply']
    s.backfill.queue(p)
    assert [j for j in s.store.rows('SELECT * FROM community_jobs') if json.loads(j['snapshot'])['payload']['kind']=='reply']==before
    comments=[r for r in s.backfill.state()['items'] if r['kind']=='reply']
    assert comments and all(r['status']=='cancelled' for r in comments)
    assert not f.sent


def test_posts_only_prepares_at_midnight_and_queues_one_at_one(supply):
    s,f,a,p,now,m=supply
    switch(s,p);s.daily.control(p,'enable')
    f.discover=lambda *args:(_ for _ in ()).throw(AssertionError('comments disabled: no discovery'))
    generated=m.generate
    def article_only(*args):
        assert args[2]==[] and args[5]==0
        return generated(*args)
    m.generate=article_only
    for offset in range(2):
        now[0]=datetime(2026,10,15+offset,0,0,tzinfo=SHANGHAI).timestamp()
        s.materials.tick();s.daily.tick()
        assert len(s.state()['posts'])==offset
        assert m.calls==offset+1
        now[0]+=3600;s.daily.tick();s.daily.tick()
        posts=s.state()['posts']
        assert len(posts)==offset+1 and all(x['payload']['kind']=='thread' for x in posts)
    assert not f.sent
