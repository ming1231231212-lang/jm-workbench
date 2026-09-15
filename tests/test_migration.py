import json
import sqlite3
from jm_workbench.core.config import Config
from jm_workbench.core.db import Store
from jm_workbench.services.configuration import Configuration
from jm_workbench.services.migrate import import_legacy

def test_import_is_read_only_and_does_not_approve_or_execute(tmp_path):
    root=tmp_path/'old'
    (root/'f_layer').mkdir(parents=True)
    path=root/'f_layer'/'f_layer.db'
    with sqlite3.connect(path) as db:
        db.executescript('''CREATE TABLE adult_candidates(video_id TEXT,payload TEXT,updated_at REAL);
        CREATE TABLE f_publish_videos(video_id TEXT,reply_text TEXT,publish_time TEXT);
        CREATE TABLE adult_control(id INTEGER,account_id TEXT,risk INTEGER);''')
        db.execute('INSERT INTO adult_candidates VALUES(?,?,?)',('video123',json.dumps({'caption':'本店成人用品库存','author_id':'author123'}),1))
        db.execute('INSERT INTO f_publish_videos VALUES(?,?,?)',('video123','历史评论','2026-09-14 21:00:00'))
        db.execute("INSERT INTO adult_control VALUES(1,'oldaccount',1)")
    before=path.read_bytes()
    cfg=Configuration(Config(tmp_path/'new'),Store(tmp_path/'new.db'))
    result=import_legacy(cfg,root,tmp_path/'profile')
    assert result=={'candidates':1,'history':1,'attempts':0}
    assert cfg.store.rows('SELECT decision FROM evidence')[0]['decision']=='legacy'
    assert cfg.store.objects('account')[0]['connection']=='unverified'
    assert not cfg.store.rows('SELECT * FROM runs')
    assert cfg.store.rows('SELECT * FROM risk')
    import_legacy(cfg,root,tmp_path/'profile')
    assert len(cfg.store.rows('SELECT * FROM evidence'))==1
    assert path.read_bytes()==before
