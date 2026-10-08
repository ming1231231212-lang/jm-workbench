"""Assemble an allowlisted, offline Windows x64 bundle from verified build inputs.

Run from an ordinary build Python; recipients do not need Python, pip or Node.
The downloads directory contains the official embedded Python archive and wheels.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from email.parser import Parser
from packaging.specifiers import SpecifierSet
from packaging.tags import cpython_tags, compatible_tags
from packaging.utils import parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]
PYTHON_FILE = 'python-3.13.16-embed-amd64.zip'
PYTHON_SHA256 = '97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(2 ** 20), b''):
            h.update(block)
    return h.hexdigest()


def copy_source(source, target, suffixes):
    for path in source.rglob('*'):
        if path.is_file() and path.suffix in suffixes and '__pycache__' not in path.parts:
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)


def install_wheels(wheels, site):
    """Unpack verified binary wheels without host-bound pip script launchers/direct_url files."""
    tags = set(cpython_tags((3, 13), abis=['cp313'], platforms=['win_amd64']))
    tags.update(compatible_tags((3, 13), interpreter='cp313', platforms=['win_amd64']))
    lock = (ROOT / 'packaging/requirements-windows.lock').read_text(encoding='utf-8')
    for wheel in wheels:
        if not parse_wheel_filename(wheel.name)[3].intersection(tags):
            raise ValueError('Incompatible Windows CPython wheel: ' + wheel.name)
        if 'sha256:' + digest(wheel) not in lock:
            raise ValueError('Wheel is not in the reviewed dependency lock: ' + wheel.name)
        with zipfile.ZipFile(wheel) as package:
            metadata_path = next(n for n in package.namelist() if n.endswith('.dist-info/METADATA'))
            metadata = Parser().parsestr(package.read(metadata_path).decode('utf-8'))
            if '3.13.16' not in SpecifierSet(metadata.get('Requires-Python', '')):
                raise ValueError('Python version outside wheel requirements: ' + wheel.name)
            for member in package.infolist():
                if member.is_dir():
                    continue
                parts = Path(member.filename).parts
                if len(parts) > 2 and parts[0].endswith('.data') and parts[1] in ('purelib', 'platlib'):
                    parts = parts[2:]
                destination = (site / Path(*parts)).resolve()
                if not destination.is_relative_to(site.resolve()):
                    raise ValueError('Unsafe wheel path')
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(package.read(member))


def audit(target):
    forbidden = {'var', 'outputs', '.git', '.venv', 'node_modules', '__pycache__', 'browser_profiles', 'User Data', 'cookiesFile', 'videoFile'}
    for path in target.rglob('*'):
        relative = path.relative_to(target)
        unexpected = forbidden.intersection(relative.parts)
        if relative.parts[0] == 'runtime':
            unexpected.discard('node_modules')  # Official Playwright/Patchright driver dependencies.
        if unexpected:
            raise ValueError(f'Private/build directory in release: {relative}')
        if path.is_file() and (path.suffix in ('.db', '.sqlite', '.sqlite3', '.log') or path.name in ('config.local.json', 'connection.json', '.env')):
            raise ValueError(f'Private state in release: {relative}')
        if path.is_file() and relative.parts[0] in ('app', 'vendor') and path.suffix in ('.py', '.js', '.html', '.json', '.md'):
            text = path.read_text(encoding='utf-8-sig')
            for marker in ('C:\\Users\\70942', 'D:\\BrainAgent', 'D:\\Codex', 'BDUSS=', 'STOKEN=', 'ghp_', 'github_pat_'):
                if marker in text:
                    raise ValueError(f'Private machine reference or credential marker in {relative}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--downloads', type=Path, required=True)
    parser.add_argument('--browser', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--refresh-source', action='store_true')
    args = parser.parse_args()
    target = args.output.resolve()
    if target.exists() and not args.refresh_source:
        raise ValueError('Use a new empty staging directory; no recursive deletion is performed')
    target.mkdir(parents=True, exist_ok=True)
    if not args.refresh_source:
        archive = args.downloads / PYTHON_FILE
        if digest(archive) != PYTHON_SHA256:
            raise ValueError('Official Python archive checksum mismatch')
        with zipfile.ZipFile(archive) as package:
            package.extractall(target / 'runtime')
        wheels = sorted(p for p in (args.downloads / 'wheels').glob('*.whl') if parse_wheel_filename(p.name)[0] != 'av')
        if not wheels:
            raise ValueError('No dependency wheels supplied')
        install_wheels(wheels, target / 'runtime/site-packages')
        browser_folders = list(args.browser.glob('chromium-*'))
        if len(browser_folders) != 1:
            raise ValueError('Supply one verified Playwright Chromium distribution')
        shutil.copytree(browser_folders[0], target / 'browser' / browser_folders[0].name)
        wheel_manifest = [{'file': p.name, 'sha256':digest(p)} for p in wheels]
        (target / 'DEPENDENCIES.json').write_text(json.dumps({'python': {'file':PYTHON_FILE, 'sha256':PYTHON_SHA256,
            'source':'https://www.python.org/ftp/python/3.13.16/'}, 'wheels':wheel_manifest}, indent=2), encoding='utf-8')
    (target / 'runtime/python313._pth').write_text('python313.zip\n.\nsite-packages\n../app\nimport site\n', encoding='utf-8')
    copy_source(ROOT / 'jm_workbench', target / 'app/jm_workbench', {'.py', '.js', '.css', '.html', '.json'})
    copy_source(ROOT / 'vendor/sau', target / 'vendor/sau', {'.py', '.js', '.json', '.md'})
    shutil.copyfile(ROOT / 'vendor/sau/LICENSE', target / 'vendor/sau/LICENSE')
    shutil.copyfile(ROOT / 'packaging/使用说明.html', target / '使用说明.html')
    shutil.copyfile(ROOT / 'packaging/THIRD_PARTY_NOTICES.md', target / 'THIRD_PARTY_NOTICES.md')
    shutil.copyfile(ROOT / 'docs/windows-portable.md', target / '维护说明.md')
    codec_sources = args.downloads / 'codec-sources'
    if not (codec_sources / 'SOURCES.json').is_file():
        raise ValueError('Fetch corresponding LGPL source archives with packaging/collect_codec_sources.py first')
    shutil.copytree(codec_sources, target / 'third-party-sources', dirs_exist_ok=True)
    compiler = Path(r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe')
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64', '/reference:System.Windows.Forms.dll',
                    '/out:' + str(target / 'JM工作台.exe'), str(ROOT / 'packaging/Launcher.cs')], check=True)
    for name in ('退出工作台.exe', '环境检查.exe'):
        shutil.copyfile(target / 'JM工作台.exe', target / name)
    audit(target)
    manifest = {p.relative_to(target).as_posix():digest(p) for p in sorted(target.rglob('*')) if p.is_file() and p.name != 'FILES.sha256.json'}
    (target / 'FILES.sha256.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'bundle':str(target),'files':len(manifest),'bytes':sum(p.stat().st_size for p in target.rglob('*') if p.is_file())}, ensure_ascii=False))


if __name__ == '__main__':
    main()
