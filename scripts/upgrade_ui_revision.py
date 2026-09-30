"""Offline upgrade of queued snapshots after a web/publishing-only change.

Requires an exact backup of the old package. Core execution/policies/adapters must
be byte-identical. Refuses running or uncertain operations, and backs up the DB.
"""
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from jm_workbench.core.config import revision
from jm_workbench.core.instance import InstanceLock


def compare_execution(old_package,new_package):
    for directory in ['core','services','policies','adapters']:
        before=old_package/directory;after=new_package/directory
        if not before.is_dir() or not after.is_dir():raise ValueError('Missing execution source backup')
        old={p.relative_to(before):p.read_bytes() for p in before.rglob('*') if p.suffix in ('.py','.js')}
        new={p.relative_to(after):p.read_bytes() for p in after.rglob('*') if p.suffix in ('.py','.js')}
        if not old or old!=new:raise ValueError('Execution sources changed: '+directory)


def migrate(db_path,previous,current,backup_path,apply=False):
    with sqlite3.connect(db_path) as db:
        db.row_factory=sqlite3.Row
        if db.execute("SELECT 1 FROM runs WHERE state='running'").fetchone() or db.execute("SELECT 1 FROM attempts WHERE state IN ('reserved','unknown')").fetchone():
            raise ValueError('Running or uncertain comment operation; no migration')
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='publish_jobs'").fetchone() and db.execute("SELECT 1 FROM publish_jobs WHERE state IN ('running','unknown')").fetchone():
            raise ValueError('Running or uncertain publication; no migration')
        rows=list(db.execute("SELECT id,snapshot FROM runs WHERE state IN ('queued','waiting')"))
        changes=[]
        for row in rows:
            snapshot=json.loads(row['snapshot'])
            if snapshot['revision']==current:continue
            if snapshot['revision']!=previous:raise ValueError('Active queue has a different revision')
            snapshot['revision']=current;changes.append((json.dumps(snapshot,ensure_ascii=False,separators=(',',':')),row['id']))
        if apply:
            backup_path.parent.mkdir(parents=True,exist_ok=True)
            if backup_path.exists():raise ValueError('Backup path already exists')
            with sqlite3.connect(backup_path) as dest:db.backup(dest)
            db.execute('BEGIN IMMEDIATE')
            db.executemany('UPDATE runs SET snapshot=? WHERE id=?',changes)
        return {'active_queues':len(rows),'revision_updates':len(changes),'applied':apply}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home',type=Path,required=True)
    parser.add_argument('--previous-revision',required=True)
    parser.add_argument('--old-package',type=Path,required=True)
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    compare_execution(args.old_package,ROOT/'jm_workbench')
    lock=InstanceLock(args.home/'worker.lock')
    try:print(json.dumps(migrate(args.home/'jm.db',args.previous_revision,revision(),args.backup,args.apply)))
    finally:lock.close()


if __name__=='__main__':main()
