"""Split a verified ZIP for bounded parallel upload; the final download stays a single ZIP."""
import argparse
import hashlib
import json
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('archive',type=Path)
parser.add_argument('parts',type=Path)
args=parser.parse_args()
args.parts.mkdir(parents=True,exist_ok=False)
pieces=[];whole=hashlib.sha256()
with args.archive.open('rb') as source:
    index=0
    while data:=source.read(24*1024*1024):
        name=f'jm-v1.1.0-upload-part-{index:02}.bin'
        (args.parts/name).write_bytes(data)
        pieces.append({'name':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        whole.update(data);index+=1
manifest={'tag':'v1.1.0','asset':args.archive.name,'bytes':args.archive.stat().st_size,
          'sha256':whole.hexdigest(),'parts':pieces}
(Path(__file__).parent/'release-upload-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(f'Prepared {len(pieces)} exact binary parts; whole SHA256 {whole.hexdigest()}')
