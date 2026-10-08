"""Import only audited MIT source files, never a user's installation data."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

FILES = ['LICENSE', 'sau_backend.py', 'jm_publish_guard.py', 'myUtils/auth.py', 'myUtils/login.py',
         'myUtils/postVideo.py', 'uploader/base_video.py', 'uploader/xhs_uploader/main.py']
FILES += ['uploader/' + name + '/main.py' for name in ('douyin_uploader', 'ks_uploader', 'tencent_uploader', 'xiaohongshu_uploader')]
FILES += ['utils/' + name for name in ('base_social_media.py', 'constant.py', 'files_times.py', 'log.py', 'login_qrcode.py', 'stealth.min.js')]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    destination = Path(__file__).resolve().parents[1] / 'vendor/sau'
    manifest = {}
    for name in FILES:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.source / name, target)
        manifest[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    helper = destination / 'utils/base_social_media.py'
    helper.write_text(helper.read_text(encoding='utf-8-sig').replace('Path(BASE_DIR / "utils/stealth.min.js")', 'Path(__file__).with_name("stealth.min.js")'), encoding='utf-8')
    helper = destination / 'uploader/xhs_uploader/main.py'
    text = helper.read_text(encoding='utf-8-sig').replace('LOCAL_CHROME_HEADLESS', 'LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH', 1)
    text = text.replace('pathlib.Path(BASE_DIR / "utils/stealth.min.js")', 'pathlib.Path(__file__).resolve().parents[2] / "utils/stealth.min.js"')
    text = text.replace('chromium.launch(headless=LOCAL_CHROME_HEADLESS)', 'chromium.launch(headless=LOCAL_CHROME_HEADLESS, executable_path=LOCAL_CHROME_PATH)')
    helper.write_text(text, encoding='utf-8')
    (destination / 'UPSTREAM.json').write_text(json.dumps({'project':'https://github.com/dreammis/social-auto-upload',
        'license':'MIT', 'source_sha256':manifest, 'changes':['Guarded single submit via JM patch',
        'Data and browser paths injected by portable wrapper', 'Static script paths follow vendor code']}, indent=2), encoding='utf-8')
    print(f'Imported {len(FILES)} source files. No databases, cookies or profiles.')

if __name__ == '__main__':
    main()
