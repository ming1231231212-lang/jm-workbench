import argparse
import uvicorn
from .web.app import create_app

def main():
    parser = argparse.ArgumentParser(description='JM工作台本机服务')
    parser.add_argument('--port', type=int, default=8776)
    parser.add_argument('--home', default=None)
    parser.add_argument('--no-worker', action='store_true', help='用于UI验收，不启动真实任务')
    args = parser.parse_args()
    uvicorn.run(create_app(args.home, worker=not args.no_worker), host='127.0.0.1', port=args.port, access_log=False)

if __name__ == '__main__':
    main()
