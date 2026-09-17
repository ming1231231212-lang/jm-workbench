import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from jm_workbench.core.db import dumps
from scripts.requeue_history import requeue_history
from test_engine import rig, batch, continue_batch, row_for, run_when_due


@pytest.fixture
def historical(batch):
    child = continue_batch(batch)
    ident = 'historical1234'
    source = batch.original
    with batch.store.connect() as db:
        db.execute('INSERT INTO runs(id,task_id,account_id,platform,state,snapshot,progress,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',
                   (ident,source['task_id'],source['account_id'],'ks','completed',source['snapshot'],dumps({'collected':7,'pending':[]}),1,1))
    a = dict(batch.items[0],video_id='freshvideo1',author_id='freshauthor1')
    b = dict(batch.items[0],video_id='freshvideo2')  # old contacted author, but a different video
    items = [batch.items[0],batch.items[1],a,a,b,
             dict(a,video_id='unrelated1',caption='今天出门旅游'),
             dict(a,video_id='wrongorigin1',source={'kind':'search','query':'别的关键词'})]
    for item in items:
        batch.store.add_evidence(ident,'ks',item,'skipped','旧规则排除')
    batch.history_id, batch.child_id = ident, child
    batch.new_items = [a,b]
    return batch


def snapshot(db):
    return {table:db.rows('SELECT * FROM '+table) for table in ('runs','evidence','attempts','continuations','objects','events')}


def test_preview_does_not_modify_and_merge_preserves_original_queue(historical):
    b = historical
    before = snapshot(b.store)
    preview = requeue_history(b.cfg,b.history_id,now=b.clock.now)
    assert preview['summary']==dict(source_run_id=b.history_id,records=7,unique=6,matched=4,added=2,already_queued=1,contacted=1,rejected=2)
    assert snapshot(b.store)==before
    pending = row_for(b,b.child_id)['progress']['pending']
    result = requeue_history(b.cfg,b.history_id,apply=True,now=b.clock.now)
    assert result['created'] and result['summary']==preview['summary']
    merged = row_for(b,b.child_id)['progress']['pending']
    assert merged[:len(pending)]==pending and len(merged)==7
    assert next(p for p in merged if p['video_id']=='freshvideo2')['not_before']>b.clock.now+6*86400
    assert len({p['video_id'] for p in merged})==len(merged)
    after = snapshot(b.store)
    assert before['attempts']==after['attempts'] and before['objects']==after['objects']
    original = lambda state:next(r for r in state['runs'] if r['id']==b.history_id)
    assert original(before)==original(after)
    old_child = next(r for r in before['runs'] if r['id']==b.child_id)
    new_child = next(r for r in after['runs'] if r['id']==b.child_id)
    assert old_child['snapshot']==new_child['snapshot']
    assert len(after['evidence'])==len(before['evidence'])+2
    assert b.fake.sends==1


def test_concurrent_history_rechecks_merge_once(historical):
    b = historical
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda _:requeue_history(b.cfg,b.history_id,apply=True,now=b.clock.now),range(3)))
    assert sum(r['created'] for r in results)==1
    assert len(row_for(b,b.child_id)['progress']['pending'])==7
    assert len(b.store.rows('SELECT * FROM continuations WHERE source_run_id=?',(b.history_id,)))==1
    assert b.fake.sends==1


@pytest.mark.parametrize('block',['risk','unknown','running','identity','snapshot','no_queue'])
def test_recheck_refuses_incompatible_or_unsafe_merge(historical,block):
    b = historical
    with b.store.connect() as db:
        if block=='risk':
            db.execute("INSERT INTO risk VALUES('ks','平台限制',1)")
        elif block=='unknown':
            db.execute("INSERT INTO attempts(id,platform,video_id,state,created) VALUES('unknown','ks','uncertain1','unknown',1)")
        elif block=='running':
            db.execute("UPDATE runs SET state='running' WHERE id=?",(b.child_id,))
        elif block=='no_queue':
            db.execute("UPDATE runs SET state='paused' WHERE id=?",(b.child_id,))
        elif block=='identity':
            raw=json.loads(db.execute('SELECT snapshot FROM runs WHERE id=?',(b.history_id,)).fetchone()['snapshot'])
            raw['account']['identity']='otheridentity'
            db.execute('UPDATE runs SET snapshot=? WHERE id=?',(dumps(raw),b.history_id))
        elif block=='snapshot':
            raw=json.loads(db.execute('SELECT snapshot FROM runs WHERE id=?',(b.child_id,)).fetchone()['snapshot'])
            raw['revision']='old-code'
            db.execute('UPDATE runs SET snapshot=? WHERE id=?',(dumps(raw),b.child_id))
    before=snapshot(b.store)
    with pytest.raises(ValueError):
        requeue_history(b.cfg,b.history_id,apply=True,now=b.clock.now)
    assert snapshot(b.store)==before and b.fake.sends==1


def test_missing_source_and_changed_source_keyword_are_not_reconstructed(historical):
    b=historical
    with b.store.connect() as db:
        raw=json.loads(db.execute('SELECT snapshot FROM runs WHERE id=?',(b.history_id,)).fetchone()['snapshot'])
        raw['task']['keywords']=['情趣用品店']
        db.execute('UPDATE runs SET snapshot=? WHERE id=?',(dumps(raw),b.history_id))
    result=requeue_history(b.cfg,b.history_id,apply=True,now=b.clock.now)
    assert result['summary']['added']==0 and result['summary']['rejected']==6
    assert len(row_for(b,b.child_id)['progress']['pending'])==5


def test_merged_candidates_follow_normal_detail_and_send_guards(historical):
    b=historical
    requeue_history(b.cfg,b.history_id,apply=True,now=b.clock.now)
    all_items=b.items+b.new_items
    b.fake.search=lambda *args:pytest.fail('历史补发不能重新搜索')
    def detail(self,vid):
        item=next(item for item in all_items if item['video_id']==vid)
        return dict(item,source={'kind':'detail'},detail_verified=True,observed_at=b.clock.now)
    b.fake.detail=detail
    for _ in range(5):
        run_when_due(b,b.child_id)
    assert b.fake.sends==5  # daily cap, remaining candidates retained
    row=row_for(b,b.child_id)
    assert row['state']=='waiting' and len(row['progress']['pending'])==3
    # The new target loses permission before its turn; it cannot be sent.
    b.new_items[0]['can_comment']=False
    for _ in range(3):
        run_when_due(b,b.child_id)
    assert not b.store.rows('SELECT * FROM attempts WHERE video_id=?',('freshvideo1',))
