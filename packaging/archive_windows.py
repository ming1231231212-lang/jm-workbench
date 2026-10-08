"""Verify every staged file, then create a recipient ZIP and SHA256 sidecar."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bundle',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
root=args.bundle.resolve();destination=args.output.resolve()
if destination.exists():raise ValueError('Do not overwrite an existing release archive')
destination.parent.mkdir(parents=True,exist_ok=True)
def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(2**20),b''):result.update(block)
    return result.hexdigest()
manifest=json.loads((root/'FILES.sha256.json').read_text(encoding='utf-8'))
actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
if actual!=set(manifest)|{'FILES.sha256.json'}:raise ValueError('Unexpected files appeared after the manifest was built')
for name,expected in manifest.items():
    if digest(root/name)!=expected:raise ValueError('File changed after staging: '+name)
with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
    for name in sorted(actual):archive.write(root/name,'JMWorkbench/'+name)
with zipfile.ZipFile(destination) as archive:
    broken=archive.testzip()
    if broken:raise ValueError('ZIP verification failed: '+broken)
sha=digest(destination)
destination.with_suffix('.zip.sha256').write_text(sha+'  '+destination.name+'\n',encoding='utf-8')
print(json.dumps({'file':str(destination),'sha256':sha,'bytes':destination.stat().st_size,'entries':len(actual),'verified':True},ensure_ascii=False))
