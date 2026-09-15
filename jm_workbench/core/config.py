import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def revision():
    digest = hashlib.sha256()
    for path in sorted((ROOT / 'jm_workbench').rglob('*')):
        if path.suffix in ('.py', '.js', '.css', '.html'):
            digest.update(path.relative_to(ROOT).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


class Config:
    def __init__(self, home=None):
        self.home = Path(home or os.environ.get('JM_HOME', ROOT / 'var')).resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / 'config.local.json'
        self.values = {'chrome_path': r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                       'crawler_root': '', 'crawler_python': ''}
        if self.path.exists():
            self.values.update(json.loads(self.path.read_text(encoding='utf-8-sig')))

    def save(self, values):
        self.values.update(values)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.values, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(self.path)

    def crawler_ready(self):
        root = Path(self.values['crawler_root'])
        return (root / 'main.py').is_file() and Path(self.values['crawler_python']).is_file()
