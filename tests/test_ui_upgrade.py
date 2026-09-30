import json
import sqlite3
import pytest
from jm_workbench.core.db import Store
from scripts.upgrade_ui_revision import migrate,compare_execution


def test_upgrade_changes_only_revision_and_preserves_pending_and_receipts(tmp_path):
    db=tmp_path/'test.db';store=Store(db);backup=tmp_path/'backup.db'
    snapshot={'revision':'old','account':{'id':'fixed'},'task':{'comments_per_video':1}}
    with store.connect() as con:
        con.execute("INSERT INTO runs(id,state,snapshot,progress) VALUES('one','waiting',?,?)",(json.dumps(snapshot),json.dumps({'pending':[{'video_id':'keep-me'}],'sent':9})))
        con.execute("INSERT INTO attempts(id,state) VALUES('sent-1','sent')")
    before=store.rows('SELECT * FROM runs')[0]
    assert migrate(db,'old','new',backup)['revision_updates']==1
    assert store.rows('SELECT * FROM runs')[0]==before and not backup.exists()
    assert migrate(db,'old','new',backup,True)['revision_updates']==1
    after=store.rows('SELECT * FROM runs')[0]
    changed=json.loads(after['snapshot']);assert changed.pop('revision')=='new';assert changed=={k:v for k,v in snapshot.items() if k!='revision'}
    after['snapshot']=before['snapshot'];assert after==before
    assert store.rows('SELECT state FROM attempts')==[{'state':'sent'}]
    with sqlite3.connect(backup) as con:assert json.loads(con.execute('SELECT snapshot FROM runs').fetchone()[0])['revision']=='old'


@pytest.mark.parametrize('state',['running','unknown'])
def test_upgrade_refuses_inflight_or_uncertain(tmp_path,state):
    db=tmp_path/'test.db';store=Store(db)
    with store.connect() as con:
        if state=='running':con.execute("INSERT INTO runs(id,state,snapshot) VALUES('one','running','{}')")
        else:con.execute("INSERT INTO attempts(id,state) VALUES('one','unknown')")
    with pytest.raises(ValueError):migrate(db,'old','new',tmp_path/'backup.db',True)
    assert not (tmp_path/'backup.db').exists()


def test_execution_source_difference_blocks_web_migration(tmp_path):
    old=tmp_path/'old';new=tmp_path/'new'
    for directory in ['core','services','policies','adapters']:
        for root in [old,new]:
            (root/directory).mkdir(parents=True);(root/directory/'code.py').write_text('unchanged',encoding='utf-8')
    compare_execution(old,new)
    (new/'policies/code.py').write_text('changed rule',encoding='utf-8')
    with pytest.raises(ValueError,match='policies'):compare_execution(old,new)
