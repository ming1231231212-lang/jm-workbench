"""CI: reconstruct the exact tested local ZIP, verify it, upload, then remove temporary parts."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time

manifest=json.loads((Path(__file__).parent/'release-upload-manifest.json').read_text())
tag=manifest['tag']
def gh(*args,**kwargs):return subprocess.run(['gh',*args],check=True,**kwargs)
deadline=time.monotonic()+1500
while True:
    data=json.loads(gh('release','view',tag,'--json','isDraft,assets',capture_output=True,text=True).stdout)
    if not data['isDraft']:raise RuntimeError('Assembly only operates on this draft release')
    assets={a['name']:a for a in data['assets']}
    complete=sum(p['name'] in assets and assets[p['name']]['size']==p['bytes'] and assets[p['name']]['state']=='uploaded' for p in manifest['parts'])
    print(f'Uploaded parts: {complete}/{len(manifest["parts"])}',flush=True)
    if complete==len(manifest['parts']):break
    if time.monotonic()>deadline:raise TimeoutError('Waiting for source upload parts timed out')
    time.sleep(15)
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);archive=root/manifest['asset'];whole=hashlib.sha256()
    with archive.open('wb') as output:
        for part in manifest['parts']:
            gh('release','download',tag,'--pattern',part['name'],'--dir',str(root))
            data=(root/part['name']).read_bytes()
            if len(data)!=part['bytes'] or hashlib.sha256(data).hexdigest()!=part['sha256']:
                raise ValueError('Downloaded part verification failed: '+part['name'])
            output.write(data);whole.update(data)
    if archive.stat().st_size!=manifest['bytes'] or whole.hexdigest()!=manifest['sha256']:
        raise ValueError('Reconstructed archive differs from tested local artifact')
    gh('release','upload',tag,str(archive),'--clobber')
    print('Exact tested ZIP uploaded; SHA256 '+whole.hexdigest(),flush=True)
    for part in manifest['parts']:
        gh('release','delete-asset',tag,part['name'],'--yes')
    print('Temporary parts removed. Draft contains one complete ZIP.',flush=True)
