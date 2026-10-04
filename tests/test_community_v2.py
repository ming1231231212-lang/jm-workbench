import json
from datetime import datetime
from test_community import setup, account
from jm_workbench.community.models import CommunityPost, DailyPlan
from jm_workbench.community.service import SHANGHAI


def test_state_exposes_plan_relationship_and_read_only_totals(setup):
    _, s, fake, clock = setup
    clock[0] = datetime(2026, 10, 4, 12, tzinfo=SHANGHAI).timestamp()
    a = account(s, 'tieba')
    p = s.daily.save(DailyPlan(name='测试每日计划',account_id=a,board='人工智能',rules_note='本地模拟的社区规则与目标位置记录，不会真实发送'))['id']
    post = s.save(CommunityPost(request_id='readonly-plan-item',title='测试计划中的主题帖',body='这是用于验证数据展示的本地主题帖正文。',targets=[{'account_id':a,'destination':'人工智能'}]))['id']
    with s.store.connect(True) as db:
        db.execute('INSERT INTO community_plan_items VALUES(?,?,?,?,?)',(p,'2026-10-04','thread','material',post))
    with s.store.connect() as db:
        before='\n'.join(db.iterdump())
    state=s.state()
    row=next(r for r in state['posts'] if r['id']==post)
    assert row['plan_id']==p and row['plan_day']=='2026-10-04'
    assert state['summary']['day']=='2026-10-04'
    assert state['post_total']==1 and state['post_limit']==200
    assert state['summary']['thread_submitted']==0 and not fake.sent
    with s.store.connect() as db:
        assert '\n'.join(db.iterdump())==before


def test_daily_summary_counts_jobs_outside_recent_200_without_claiming_visibility(setup):
    _, s, _, clock=setup
    clock[0]=datetime(2026,10,4,0,1,tzinfo=SHANGHAI).timestamp()
    a=account(s,'tieba')
    with s.store.connect(True) as db:
        for i in range(205):
            payload={'kind':'reply','title':'本地测试','body':'正文','targets':[{'account_id':a,'destination':'https://tieba.baidu.com/p/123456'}]}
            db.execute('INSERT INTO community_posts VALUES(?,?,?,?,?,?)',(str(i),'req-'+str(i),json.dumps(payload),'active',clock[0]+i,clock[0]+i))
            snap={'payload':payload,'account':{'name':'fixture'},'destination':'https://tieba.baidu.com/p/123456'}
            db.execute('INSERT INTO community_jobs(id,post_id,platform,account_id,identity,digest,state,snapshot,receipt,due,started,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',('j'+str(i),str(i),'tieba',a,'fixture',str(i),'submitted',json.dumps(snap),'{}',clock[0],clock[0],clock[0],clock[0]))
        # Previous Shanghai date and manually registered links are separate from accepted submissions.
        db.execute("UPDATE community_jobs SET started=? WHERE id='j0'",(clock[0]-120,))
        db.execute("UPDATE community_jobs SET state='recorded' WHERE id='j1'")
    state=s.state()
    assert state['post_total']==205 and len(state['posts'])==200
    assert state['summary']['reply_submitted']==203
    assert state['summary']['recorded']==1
