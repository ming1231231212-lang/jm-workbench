"""Record exact binary artifacts in the portable runtime lockfile."""
import argparse
import hashlib
from pathlib import Path
from packaging.utils import parse_wheel_filename

parser=argparse.ArgumentParser()
parser.add_argument('directory', type=Path)
args=parser.parse_args()
lines=['# Windows x64 / CPython 3.13. Binary artifacts are pinned with SHA256.']
for path in sorted(args.directory.glob('*.whl')):
    name,version,_,_=parse_wheel_filename(path.name)
    if name == 'av':
        continue
    lines.append(f'{name}=={version} --hash=sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}')
(Path(__file__).parent/'requirements-windows.lock').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(f'Locked {len(lines)-1} wheel artifacts')
