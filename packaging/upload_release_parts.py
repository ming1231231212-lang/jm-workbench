"""Upload only the files declared in this release's manifest; at most six connections."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess

parser=argparse.ArgumentParser()
parser.add_argument('--gh',required=True)
parser.add_argument('--parts',type=Path,required=True)
args=parser.parse_args()
manifest=json.loads((Path(__file__).parent/'release-upload-manifest.json').read_text())
def upload(part):
    path=args.parts/part['name']
    if path.stat().st_size!=part['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=part['sha256']:
        raise ValueError('Part changed before upload')
    subprocess.run([args.gh,'release','upload',manifest['tag'],str(path),'--clobber'],check=True)
    print('Uploaded '+part['name'],flush=True)
with ThreadPoolExecutor(max_workers=6) as pool:
    list(pool.map(upload,manifest['parts']))
print('All temporary parts uploaded',flush=True)
