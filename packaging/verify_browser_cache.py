"""Verify a clean browser cache against Google's official ZIP directory via HTTPS ranges."""
import argparse
import io
import json
from pathlib import Path
import urllib.request
import zipfile
import zlib

URL = 'https://storage.googleapis.com/chrome-for-testing-public/149.0.7827.55/win64/chrome-win64.zip'

class RemoteZip(io.RawIOBase):
    def __init__(self):
        with urllib.request.urlopen(urllib.request.Request(URL, method='HEAD'), timeout=20) as response:
            self.size = int(response.headers['Content-Length'])
        self.position = 0
    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.position
    def seek(self, offset, whence=0):
        self.position = offset + (0 if whence == 0 else self.position if whence == 1 else self.size)
        return self.position
    def read(self, size=-1):
        end = self.size if size < 0 else min(self.size, self.position + size)
        if end <= self.position: return b''
        request = urllib.request.Request(URL, headers={'Range':f'bytes={self.position}-{end-1}'})
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 206 or response.headers.get('Content-Range') != f'bytes {self.position}-{end-1}/{self.size}':
                raise ValueError('Server did not honor the exact verified archive range')
            data = response.read()
        if len(data) != end - self.position: raise ValueError('Truncated archive range')
        self.position = end
        return data

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cache',type=Path)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    entries=[]
    with zipfile.ZipFile(RemoteZip()) as remote:
        for member in remote.infolist():
            if member.is_dir(): continue
            path=args.cache/member.filename
            if not path.is_file() or path.stat().st_size != member.file_size:
                raise ValueError('Cache file missing or unexpected size: '+member.filename)
            crc=0
            with path.open('rb') as stream:
                for block in iter(lambda:stream.read(1024*1024),b''): crc=zlib.crc32(block,crc)
            if crc != member.CRC: raise ValueError('Official archive CRC mismatch: '+member.filename)
            entries.append(member.filename)
    extras=[p.relative_to(args.cache).as_posix() for p in args.cache.rglob('*') if p.is_file() and p.relative_to(args.cache).as_posix() not in entries and p.name not in ('INSTALLATION_COMPLETE','DEPENDENCIES_VALIDATED')]
    if extras: raise ValueError('Unexpected files in browser cache: '+repr(extras))
    args.report.write_text(json.dumps({'source':URL,'result':'passed','files':len(entries),
        'method':'Compare every uncompressed file size and CRC32 with official HTTPS ZIP central directory',
        'version':'149.0.7827.55'},indent=2),encoding='utf-8')
    print(f'Official browser ZIP metadata matches all {len(entries)} cached files; no extra user data.')

if __name__=='__main__': main()
