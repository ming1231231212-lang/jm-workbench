"""Reconcile real receipts without sending or rewriting historical outcomes."""
import json
import pytest
from datetime import datetime
from jm_workbench.community.models import CommunityPost, DailyPlan
from jm_workbench.community.service import SHANGHAI
from test_community_replies import ctx
from test_community_daily import config
from test_auto_materials import supply


def existing_receipt(s,a,n,i,kind='reply',state='recorded',identity=None,url=True):
    target='ai工具' if kind=='thread' else 'https://tieba.baidu.com/p/'+str(100000+i)
    post=s.save(CommunityPost(request_id='existing-receipt-'+str(i),kind=kind,title='已发布内容'+str(i),
        body='当时已经发布的完整正文，保留原有依据和回执，编号'+str(i),source_title='真实原帖标题',
        source_excerpt='原帖完整上下文依据',targets=[{'account_id':a,'destination':target}]))['id']
    s.launch(post)
    with s.store.connect(True) as db:
        db.execute('UPDATE community_jobs SET state=?,identity=?,started=?,updated=?,receipt=? WHERE post_id=?',
          (state,identity or s.account(a)['identity'],n[0] if state=='submitted' else 0,n[0],
           json.dumps({'url':'https://tieba.baidu.com/p/'+str(100000+i),'visibility':'user_reported'} if url else {}),post))
    return post


def test_today_receipts_link_once_keep_original_outcome_and_prevent_duplicate_six(ctx):
    s,f,a,n=ctx;n[0]=datetime(2026,10,14,15,0,tzinfo=SHANGHAI).timestamp();s.check_account(a)
    posts=[existing_receipt(s,a,n,i,'thread' if i==0 else 'reply') for i in range(6)]
    before=s.store.rows('SELECT * FROM community_jobs ORDER BY id')
    d=config(a);d.hour=1;p=s.daily.save(d)['id'];s.daily.control(p,'enable')
    assert s.daily.control(p,'sync-receipts')['linked']==6
    assert s.daily.control(p,'sync-receipts')['linked']==0
    s.daily.prepare(p,force=True);s.tick()
    assert not f.sent and len(s.state()['posts'])==6
    assert s.store.rows('SELECT * FROM community_jobs ORDER BY id')==before
    plan=s.daily.state()[0];counts=plan['days'][0]['counts']
    assert counts['thread']['recorded']==1 and counts['reply']['recorded']==5
    assert counts['thread']['submitted']==counts['reply']['submitted']==0
    assert all(x['plan_id']==p and x['plan_day']=='2026-10-14' for x in s.state()['posts'])
    assert {x['id'] for x in s.state()['posts']}==set(posts)


def test_sync_excludes_yesterday_other_identity_unknown_no_url_and_existing_plan(ctx):
    s,_,a,n=ctx;n[0]=datetime(2026,10,13,15,0,tzinfo=SHANGHAI).timestamp();s.check_account(a)
    existing_receipt(s,a,n,10)
    n[0]+=86400;s.check_account(a)
    existing_receipt(s,a,n,11,identity='other-account')
    existing_receipt(s,a,n,12,state='unknown')
    existing_receipt(s,a,n,13,url=False)
    valid=existing_receipt(s,a,n,14,state='submitted')
    p=s.daily.save(config(a))['id'];q=s.daily.save(config(a))['id']
    assert s.daily.sync_receipts(p)['linked']==1
    assert s.daily.sync_receipts(q)['linked']==0
    assert s.store.rows('SELECT post_id FROM community_plan_items')==[{'post_id':valid}]


def test_midnight_prepares_only_and_one_am_schedules(supply):
    s,f,a,p,n,m=supply
    s.daily.control(p,'pause');d=s.daily.get(p)['payload'];d.update(hour=1,minute=0)
    s.daily.save(DailyPlan(**d),p);s.daily.control(p,'enable')
    n[0]=datetime(2026,10,14,23,59,tzinfo=SHANGHAI).timestamp();s.materials.tick();s.daily.tick()
    assert m.calls==0 and not s.state()['posts']
    n[0]=datetime(2026,10,15,0,0,tzinfo=SHANGHAI).timestamp();s.materials.tick();s.daily.tick()
    assert m.calls==1 and not s.state()['posts'] and not f.sent
    n[0]=datetime(2026,10,15,0,59,tzinfo=SHANGHAI).timestamp();s.daily.tick();assert not s.state()['posts']
    n[0]+=60;s.daily.tick()
    assert len(s.state()['posts'])==6 and not f.sent


def test_earlier_web_account_records_link_without_upgrading_identity_evidence(ctx):
    s,f,a,n=ctx
    post=existing_receipt(s,a,n,30,identity='manual:'+a)
    with s.store.connect(True) as db:
        snap=json.loads(db.execute('SELECT snapshot FROM community_jobs WHERE post_id=?',(post,)).fetchone()[0])
        snap['account']['identity']='';snap['account']['version']=0
        db.execute('UPDATE community_jobs SET snapshot=? WHERE post_id=?',(json.dumps(snap),post))
    before=s.store.rows('SELECT * FROM community_jobs')
    p=s.daily.save(config(a))['id']
    assert s.daily.sync_receipts(p)['linked']==1
    assert s.store.rows('SELECT * FROM community_jobs')==before
    assert not f.sent and s.daily.state()[0]['days'][0]['counts']['reply']['recorded']==1


def test_one_am_does_not_bypass_rolling_24h_after_today_catchup(ctx):
    s,f,a,n=ctx;n[0]=datetime(2026,10,14,15,0,tzinfo=SHANGHAI).timestamp();s.check_account(a)
    for i in range(6):
        existing_receipt(s,a,n,20+i,'thread' if i==0 else 'reply');n[0]+=1801
    n[0]=datetime(2026,10,15,1,0,tzinfo=SHANGHAI).timestamp();s.check_account(a)
    d=config(a);d.hour=1;p=s.daily.save(d)['id'];s.daily.control(p,'enable');s.daily.prepare(p);s.tick()
    assert not f.sent
    queued=[j for post in s.state()['posts'] for j in post['jobs'] if j['state']=='queued']
    assert len(queued)==6
    assert min(j['due'] for j in queued)>=datetime(2026,10,15,15,0,tzinfo=SHANGHAI).timestamp()
    assert any('滚动24小时' in j['message'] for j in queued)


def test_explicit_today_continuation_preserves_old_snapshot_and_counts_each_post_once(ctx):
    s,f,a,n=ctx;p=s.daily.save(config(a))['id'];s.daily.control(p,'enable');s.daily.prepare(p,force=True)
    s.daily.control(p,'pause')
    with s.store.connect(True) as db:
        for r in db.execute('SELECT id,snapshot FROM community_jobs').fetchall():
            snap=json.loads(r['snapshot']);snap['revision']='earlier-deployment'
            db.execute('UPDATE community_jobs SET snapshot=? WHERE id=?',(json.dumps(snap),r['id']))
    before=s.store.rows('SELECT id,snapshot,receipt FROM community_jobs ORDER BY id')
    s.daily.control(p,'enable')
    assert s.daily.control(p,'continue-today')['queued']==6
    assert s.daily.control(p,'continue-today')['queued']==0
    assert s.store.rows("SELECT id,snapshot,receipt FROM community_jobs WHERE state='cancelled' ORDER BY id")==before
    counts=s.daily.state()[0]['days'][0]['counts']
    assert counts['thread']['planned']==1 and counts['reply']['planned']==5
    assert len(s.state()['posts'])==6 and not f.sent


def test_today_continuation_cannot_retry_uncertain_submission(ctx):
    s,f,a,n=ctx;p=s.daily.save(config(a))['id'];s.daily.control(p,'enable');s.daily.prepare(p,force=True)
    s.daily.control(p,'pause')
    with s.store.connect(True) as db:
        db.execute("UPDATE community_jobs SET state='unknown',started=?,receipt=?",(n[0],json.dumps({'phase':'native_submit_reserved','submitted':None})))
    before=s.store.rows('SELECT * FROM community_jobs ORDER BY id')
    s.daily.control(p,'enable')
    assert s.daily.control(p,'continue-today')['queued']==0
    assert s.store.rows('SELECT * FROM community_jobs ORDER BY id')==before and not f.sent


def test_explicit_not_sent_resolution_keeps_audit_and_allows_only_explicit_continuation(ctx):
    s,f,a,n=ctx;p=s.daily.save(config(a))['id'];s.daily.control(p,'enable');s.daily.prepare(p,force=True)
    s.daily.control(p,'pause');job=s.store.rows('SELECT id FROM community_jobs LIMIT 1')[0]['id']
    with s.store.connect(True) as db:
        db.execute("UPDATE community_jobs SET state='unknown',started=?,receipt=? WHERE id=?",(n[0],json.dumps({'phase':'fixture_unknown'}),job))
    s.resolve(job,'not_sent','已核对原任务尚未提交，保存实际准备异常依据后继续')
    old=s.job(job)
    assert old['state']=='not_sent' and old['started']==0
    receipt=json.loads(old['receipt'])
    assert receipt['previous_started']==n[0] and receipt['previous_receipt']=={'phase':'fixture_unknown'}
    assert not f.sent and not s.store.rows("SELECT id FROM community_jobs WHERE state='queued'")
    s.daily.control(p,'enable');assert s.daily.control(p,'continue-today')['queued']==6
    assert len(s.store.rows('SELECT * FROM community_backfill_continuations'))==6
    assert not f.sent


@pytest.mark.parametrize('outcome',['submitted','recorded'])
def test_historical_post_counts_on_actual_send_day_without_moving_original_item(ctx,outcome):
    s,f,a,n=ctx;n[0]=datetime(2026,10,17,1,0,tzinfo=SHANGHAI).timestamp();s.check_account(a)
    d=config(a);d.hour=1;d.replies_per_day=0;p=s.daily.save(d)['id'];s.daily.control(p,'enable')
    s.daily.prepare(p,force=True)
    original=s.store.rows('SELECT * FROM community_plan_items')
    n[0]=datetime(2026,10,19,9,0,tzinfo=SHANGHAI).timestamp()
    with s.store.connect(True) as db:
        db.execute("UPDATE community_jobs SET state=?,started=?,updated=?,receipt=?",(outcome,n[0] if outcome=='submitted' else 0,n[0],json.dumps({'url':'https://tieba.baidu.com/p/1234567'})))
        db.execute('INSERT INTO community_plan_checks VALUES(?,?,?,2,0)',(p,'2026-10-19',n[0]+1800))
    before=s.store.rows('SELECT * FROM community_jobs')
    s.daily.sync_receipts(p);s.daily.sync_receipts(p)
    assert s.store.rows('SELECT next_check FROM community_plan_checks WHERE plan_id=? AND day=?',(p,'2026-10-19'))[0]['next_check']==0
    s.daily.prepare(p,force=True)
    state=s.daily.state()[0];today=next(d for d in state['days'] if d['day']=='2026-10-19')
    assert today['counts']['thread'][outcome]==1
    assert today['counts']['thread']['planned']==1
    assert today['counts']['reply']['planned']==0
    assert today['scheduled_counts']['thread']['planned']==0
    assert today['next_check']==0
    assert state['next_action_at']==datetime(2026,10,20,1,0,tzinfo=SHANGHAI).timestamp()
    assert s.store.rows('SELECT * FROM community_plan_items')==original
    assert s.store.rows('SELECT * FROM community_jobs')==before and not f.sent
    s.recover();assert next(d for d in s.daily.state()[0]['days'] if d['day']=='2026-10-19')['counts']==today['counts']
    n[0]=datetime(2026,10,20,1,0,tzinfo=SHANGHAI).timestamp()
    assert s.daily.day_jobs(s.daily.get(p),'2026-10-20')==[]
