"""Back up and redirect only the explicitly named local entrypoints."""
import argparse
import shutil
from datetime import datetime
from pathlib import Path

def install(runtime, project):
    runtime, project=Path(runtime).resolve(),Path(project).resolve()
    backup=project/'outputs'/('legacy-backup-'+datetime.now().strftime('%Y%m%d_%H%M%S'))
    backup.mkdir(parents=True)
    entrypoints=['_adult_launch.py','_adult_guard.py','_adult_wrap.py']
    for name in entrypoints:
        path=runtime/name
        if not path.is_file():
            raise ValueError('旧入口不存在：'+name)
    legacy=runtime/'adult_outreach'/'legacy.py'
    if not legacy.is_file():
        raise ValueError('缺少旧发布保护模块')
    for name in entrypoints:
        shutil.copy2(runtime/name,backup/name)
    shutil.copy2(legacy,backup/'legacy.py')
    bridge=runtime/'_jm_bridge.py'
    if bridge.exists():
        shutil.copy2(bridge,backup/bridge.name)
    shutil.copy2(project/'scripts'/'legacy_bridge.py',bridge)
    for name in entrypoints:
        (runtime/name).write_text('"""Managed by JM工作台; old cron is observe-only."""\nfrom _jm_bridge import main\nif __name__ == "__main__":\n    raise SystemExit(main())\n',encoding='utf-8')
    text=legacy.read_text(encoding='utf-8')
    if '# JM_MANAGED_ENTRY' not in text:
        text=text.replace('def publisher_args(args):\n', 'def publisher_args(args):\n    # JM_MANAGED_ENTRY: both comment tracks now share the JM queue.\n    if not args.test:\n        from _jm_bridge import main as jm_main\n        return jm_main()\n')
        text=text.replace('def legacy_send_allowed(video_id):\n', 'def legacy_send_allowed(video_id):\n    # JM_MANAGED_ENTRY: no legacy transport may bypass JM reservations.\n    return False\n')
        legacy.write_text(text,encoding='utf-8')
    print('已备份并迁移3个旧入口与旧F6发布保护；备份：'+str(backup))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime',required=True)
    args=parser.parse_args()
    install(args.runtime,Path(__file__).resolve().parents[1])
