"""Run from outside the bundle after acceptance; test upgrade/relocation on existing data."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bundle',type=Path,required=True)
parser.add_argument('--home',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
source=args.bundle.resolve();home=args.home.resolve();out=args.output.resolve()
out.mkdir(parents=True,exist_ok=False)
relocated=out/'移动后的程序 中文 空格'
shutil.copytree(source,relocated,copy_function=os.link)
env={**os.environ,'JM_HOME':str(home),'JM_NO_BROWSER':'1','JM_BUNDLED_BROWSER':'1',
     'PATH':str(Path(os.environ['SystemRoot'])/'System32')}
checks=[]
def check(name,condition):
    assert condition,name
    checks.append(name);print('PASS '+name,flush=True)
def read():
    try:return json.loads((home/'portable-running.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}
def get(url,path):
    with urllib.request.urlopen(url+path,timeout=5) as response:return json.load(response)
try:
    check('Previous installation is stopped',not read())
    subprocess.run([str(relocated/'JM工作台.exe')],env=env,check=True,timeout=10)
    for _ in range(120):
        info=read()
        try:
            state=get(info['url'],'/api/state')
            break
        except (KeyError,OSError,ValueError):time.sleep(.5)
    else:raise AssertionError('Relocated bundle did not start')
    check('New program folder owns the same data installation',info['bundle']==str(relocated))
    check('Managed browser path follows the new program directory',Path(state['settings']['chrome_path']).is_relative_to(relocated/'browser'))
    community=get(info['url'],'/api/community/state')
    check('Account and full draft text survive relocation',len(community['accounts'])==1 and len(community['posts'])==1 and '仅用于确认内容保存' in community['posts'][0]['payload']['body'])
    check('Disabled task stays disabled after relocation',len(state['tasks'])==1 and state['tasks'][0]['enabled'] is False)
    for _ in range(60):
        video=get(info['url'],'/api/publishing/state')
        if video['connected']:break
        time.sleep(.5)
    check('Video connector and uploaded material survive relocation',video['connected'] and len(video['materials'])==1)
finally:
    subprocess.run([str(relocated/'退出工作台.exe')],env=env,check=True,timeout=10)
    for _ in range(90):
        if not read():break
        time.sleep(.5)
check('Relocated instance stops cleanly',not read())
check('Program files are not modified during use',not list(relocated.rglob('__pycache__')))
(out/'report.json').write_text(json.dumps({'result':'passed','count':len(checks),'checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
