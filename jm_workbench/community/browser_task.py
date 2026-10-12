"""Private subprocess entrypoint. Emits one result; no credentials or browser log."""
import contextlib
import io
import json
import sys
from ..core.config import Config
from .adapters import CommunityAdapter, NotSubmitted
from .bounded import LABELS


def main():
    try:
        request=json.loads(sys.stdin.buffer.read(200_000))
        action=request['action']
        if action not in LABELS: raise ValueError('unsupported action')
        adapter=CommunityAdapter(Config(sys.argv[1]))
        with contextlib.redirect_stdout(io.StringIO()):
            value=getattr(adapter, action)(*request['args'])
        result={'ok':True,'value':value}
    except Exception as ex:
        result={'ok':False,'type':type(ex).__name__,
                'message':str(ex) if isinstance(ex,NotSubmitted) else '操作未完成'}
    sys.stdout.buffer.write(json.dumps(result,ensure_ascii=False).encode())


if __name__ == '__main__': main()
