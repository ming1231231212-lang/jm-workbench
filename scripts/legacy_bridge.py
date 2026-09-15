"""Legacy schedulers observe the JM queue; they cannot enable or directly send."""
import json
import urllib.request

def main(args=None):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open('http://127.0.0.1:8776/api/state',timeout=5) as response:
            state=json.load(response)
        if state.get('name')!='JM工作台':
            raise ValueError('服务名称不符')
        print(json.dumps({'workbench':'JM工作台','action':'observe_only',
            'message':'任务由JM队列统一执行；旧定时入口不启用任务、不直接发送',
            'active_runs':sum(r['state'] in ('queued','waiting','running') for r in state['runs']),
            'risk_count':len(state['risk']),'attempt_counts':state['attempt_counts']},ensure_ascii=False))
        return 0
    except Exception as ex:
        print(json.dumps({'workbench':'JM工作台','action':'stopped','message':'JM服务未连接，旧发布入口保持停止','error_type':type(ex).__name__},ensure_ascii=False))
        return 1

if __name__=='__main__':raise SystemExit(main())
