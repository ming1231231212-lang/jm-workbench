"""Include corresponding LGPL codec sources from the exact OpenCV upstream source commit."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

COMMIT='664c0098dcb47b361f20c1d6a518653c23f5f2b5'
FILES={
 'build/aom/aom-src-v3.14.1.tar.xz':'4584f15a90efb37280bf2694674d5d44a56895ce',
 'build/ffmpeg/ffmpeg-src-n7.1.tar.xz':'84699af35b76b91c5675872c41b31ec2e88cdd85',
 'build/libvpx/libvpx-src-v1.16.0.tar.xz':'bf0ad7d97167facb41994e7fa516ce48ee1718d2',
 'build/openh264/openh264-api-headers-v2.5.0.tar.xz':'ea28d9e05f69d458ccfaf4aa985d30d366bfbc25',
 'opencv/opencv-videoio-ffmpeg.tar.xz':'72a6df0a93442ae9d2974debe68e9e6f6018a97c',
 'opencv_ffmpeg.tar.xz':'5f73134bf9a01ed659d6362fb2997ba90a559758',
}
parser=argparse.ArgumentParser()
parser.add_argument('output',type=Path)
args=parser.parse_args()
args.output.mkdir(parents=True,exist_ok=True)
def download(item):
    name,expected=item
    path=args.output/name
    path.parent.mkdir(parents=True,exist_ok=True)
    url=f'https://raw.githubusercontent.com/opencv/opencv_3rdparty/{COMMIT}/sources/{name}'
    if path.exists(): data=path.read_bytes()
    else:
        with urllib.request.urlopen(url,timeout=120) as response: data=response.read()
    actual=hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest()
    if actual!=expected: raise ValueError('Upstream source hash mismatch: '+name)
    path.write_bytes(data)
    return {'path':name,'source':url,'git_blob_sha1':expected,'sha256':hashlib.sha256(data).hexdigest()}
with ThreadPoolExecutor(max_workers=3) as pool: manifest=list(pool.map(download,FILES.items()))
(args.output/'SOURCES.json').write_text(json.dumps({'commit':COMMIT,'files':manifest},indent=2),encoding='utf-8')
print(f'Verified {len(manifest)} corresponding source archives')
