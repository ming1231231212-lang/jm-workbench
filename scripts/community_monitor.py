"""Read-only daily community audit. No publishing, login or queue mutations."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import time
import unicodedata
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SHANGHAI = timezone(timedelta(hours=8))
STATE_LABELS = {'draft': '本地草稿', 'queued': '等待执行', 'running': '提交中', 'paused': '已暂停',
                'submitted': '已提交 · 未核验公开可见', 'unknown': '结果不明', 'failed': '未提交',
                'not_sent': '已核实未发布', 'cancelled': '已取消', 'manual': '待网页发布',
                'recorded': '已登记链接 · 未核验公开可见'}
STATUS_LABELS = {'ok': '正常', 'warning': '需关注', 'error': '异常'}


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temp.write_text(text, encoding='utf-8')
    temp.replace(path)


def local_time(value):
    return datetime.fromtimestamp(value, SHANGHAI).strftime('%Y-%m-%d %H:%M:%S') if value else '—'


def text_key(value):
    return hashlib.sha256(''.join(c for c in unicodedata.normalize('NFKC', value).casefold() if c.isalnum()).encode()).hexdigest()


def collect(port=8776):
    if not 1024 <= port <= 65535:
        raise ValueError('Invalid local port')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    result = {}
    # Fixed loopback destinations, no token or credential reads, no POST.
    for name, path in [('health', '/api/health'), ('community', '/api/community/state')]:
        try:
            req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', method='GET')
            with opener.open(req, timeout=10) as response:
                value = json.load(response)
            if not isinstance(value, dict):
                raise ValueError('Invalid response')
            if name == 'health' and value.get('app_id') != 'jm-workbench':
                raise ValueError('Unexpected local service')
            if name == 'community' and not all(isinstance(value.get(k), list) for k in ('accounts', 'posts', 'plans', 'risk', 'platforms')):
                raise ValueError('Invalid community response')
            result[name] = value
        except Exception as exc:
            result[name] = None
            result[name + '_error'] = type(exc).__name__
    return result


def analyse(raw, now):
    community = raw.get('community')
    issues, jobs, accounts, plans = [], [], [], []
    def issue(key, level, message):
        issues.append({'key': key, 'level': level, 'message': message})
    if raw.get('health') is None:
        issue('service', 'error', 'JM健康接口无法读取；未重启服务或启动业务任务。')
    if community is None:
        issue('community', 'error', '社区数据无法读取，本次发送数量未知。')
    else:
        if not community.get('worker'):
            issue('worker', 'error', '社区执行器未运行。')
        for risk in community.get('risk', []):
            issue('risk:' + risk['platform'], 'error', str(risk.get('reason') or risk.get('message') or '存在平台风险锁'))
        modes = {p['id']: p.get('automatic', False) for p in community.get('platforms', [])}
        names = {p['id']: p.get('name', p['id']) for p in community.get('platforms', [])}
        for account in community.get('accounts', []):
            status = '已停用' if not account.get('enabled') else '待网站核验'
            if account.get('enabled') and modes.get(account['platform']):
                if not account.get('identity'):
                    status = '尚未绑定身份'
                    issue('account:' + account['id'], 'warning', account['name'] + '尚未绑定平台身份。')
                elif now - account.get('checked', 0) > 86400:
                    status = '上次身份检查超过24小时，当前登录未知'
                    issue('account:' + account['id'], 'warning', account['name'] + '需要重新核对登录状态。')
                else:
                    status = '24小时内检查过身份；本巡检未重新登录'
            accounts.append({'name': account['name'], 'platform': account['platform'], 'status': status,
                             'checked_at': local_time(account.get('checked', 0))})
        for plan in community.get('plans', []):
            plans.append({'name': plan.get('payload', {}).get('name', plan['id']),
                          'state': plan['state'], 'message': plan.get('message', ''),
                          'next_action_at':local_time(plan.get('next_action_at',0)), 'next_action':plan.get('next_action','')})
            is_new_draft=not plan.get('days') and plan.get('message','').startswith('配置已保存')
            if plan['state'] == 'paused' and not plan.get('message', '').startswith('用户') and not is_new_draft:
                issue('plan:' + plan['id'], 'warning', plans[-1]['name'] + '：' + plan.get('message', '计划暂停'))
            elif plan['state'] == 'enabled' and '不足' in plan.get('message', ''):
                issue('plan:' + plan['id'], 'warning', plans[-1]['name'] + '：' + plan['message'])
            if plan['state']=='enabled' and 'days' in plan:
                today=datetime.fromtimestamp(now,SHANGHAI).date().isoformat()
                d=next((d for d in plan.get('days',[]) if d['day']==today),None)
                payload=plan.get('payload',{})
                start=datetime.fromtimestamp(now,SHANGHAI).replace(hour=payload.get('hour',10),minute=payload.get('minute',0),second=0,microsecond=0).timestamp()
                if not d and now>start+900:
                    issue('plan-stalled:'+plan['id'],'error',plans[-1]['name']+'超过安排时间15分钟，仍无今日记录，请检查执行器。')
                elif d and d.get('state')=='waiting':
                    issue('plan-wait:'+plan['id'],'warning',plans[-1]['name']+'连接待恢复；下次检查 '+local_time(d.get('next_check',0)))
        seen_content, seen_target = {}, {}
        account_lookup = {a['id']: a for a in community.get('accounts', [])}
        for post in community.get('posts', []):
            payload = post['payload']
            if post.get('state') == 'draft' and not post.get('jobs'):
                for index, target in enumerate(payload.get('targets', [])):
                    account = account_lookup.get(target['account_id'], {})
                    jobs.append({'id': f"draft:{post['id']}:{index}", 'post_id': post['id'], 'title': payload['title'],
                                 'body': payload['body'], 'kind': payload.get('kind', 'thread'),
                                 'platform': account.get('platform', 'unknown'), 'account': account.get('name', ''),
                                 'platform_name': names.get(account.get('platform'), '未知平台'),
                                 'destination': target.get('destination', ''), 'state': 'draft', 'message': 'JM草稿，尚未创建发送任务。',
                                 'due': payload.get('schedule_at', 0), 'started': 0, 'updated': post.get('updated', 0),
                                 'url': '', 'visibility': 'not_submitted'})
            for job in post.get('jobs', []):
                receipt = job.get('receipt') or {}
                row = {'id': job['id'], 'post_id': post['id'], 'title': payload['title'], 'body': payload['body'],
                       'kind': payload.get('kind', 'thread'), 'platform': job['platform'],
                       'platform_name': names.get(job['platform'], job['platform']),
                       'account': job.get('account_name', ''), 'destination': job.get('destination', ''),
                       'state': job['state'], 'message': job.get('message', ''), 'due': job.get('due', 0),
                       'started': job.get('started', 0), 'updated': job.get('updated', 0),
                       'url': receipt.get('url', ''), 'visibility': receipt.get('visibility', 'unknown')}
                jobs.append(row)
                if row['state'] in ('failed', 'unknown'):
                    issue('job:' + job['id'], 'error', row['title'] + '：' + row['message'])
                elif row['state'] == 'queued' and now - row['due'] > 900:
                    issue('job:' + job['id'], 'warning', row['title'] + '：超过当前计划时间15分钟仍在等待。')
                elif row['state'] == 'running' and now - row['started'] > 900:
                    issue('job:' + job['id'], 'error', row['title'] + '：执行超过15分钟，需核对结果；不要重发。')
                elif row['state'] == 'paused' and not row['message'].startswith(('用户', '每日计划暂停')):
                    issue('job:' + job['id'], 'warning', row['title'] + '：' + row['message'])
                if row['state'] == 'submitted':
                    identity = (row['platform'], job.get('identity') or job.get('account_id'))
                    content = (*identity, text_key(row['body']))
                    if content in seen_content:
                        issue('duplicate-content:' + job['id'], 'error', row['title'] + '：发现同账号重复提交相同内容。')
                    seen_content[content] = job['id']
                    if row['kind'] == 'reply':
                        target = (*identity, row['destination'])
                        if target in seen_target:
                            issue('duplicate-target:' + job['id'], 'error', row['title'] + '：发现同账号重复评论同一目标。')
                        seen_target[target] = job['id']
    day = datetime.fromtimestamp(now, SHANGHAI).date().isoformat()
    today = [j for j in jobs if j['state'] == 'submitted' and j['started'] and
             datetime.fromtimestamp(j['started'], SHANGHAI).date().isoformat() == day]
    snapshot = {'checked_at': local_time(now), 'day': day, 'timezone': 'Asia/Shanghai',
                'service_available': raw.get('health') is not None, 'data_available': community is not None,
                'worker': bool(community and community.get('worker')), 'issues': issues,
                'counts': dict(Counter(j['state'] for j in jobs)) if community is not None else None,
                'today_submitted': dict(Counter(j['kind'] for j in today)) if community is not None else None,
                'accounts': accounts, 'plans': plans, 'jobs': jobs,
                'scope': 'JM最近200条社区内容记录。仅核对本地任务与平台回执；公开可见、浏览量、点击和转化均未核验。'}
    snapshot['status'] = 'error' if any(i['level'] == 'error' for i in issues) else 'warning' if issues else 'ok'
    return snapshot


def change_signature(report):
    # Ignore clocks, countdowns, overdue age, and expiring non-actionable activity.
    material = {'status': report['status'], 'issues': sorted((i['key'], i['level'], i['message']) for i in report['issues']),
                'jobs': sorted((j['id'], j['state'], j['url']) for j in report['jobs'])}
    return hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def markdown(report):
    text = ['# JM 社区每日巡检', '', '检查时间：' + report['checked_at'] + '（北京时间）', '',
            '状态：' + STATUS_LABELS[report['status']], '', report['scope'], '',
            daily_summary(report), '',
            '## 需要处理', '']
    text += ['- ' + i['message'] for i in report['issues']] or ['当前未发现本地任务异常。']
    text += ['', '## 任务明细', '']
    for job in report['jobs']:
        text += [f"### {job['title']}", '', f"平台：{job['platform_name']} · 目标：{job['destination'] or '个人主页'} · 状态：{STATE_LABELS.get(job['state'], job['state'])}",
                 f"计划时间：{local_time(job['due'])} · 回执可见性：{job['visibility']}", '', job['message'], '',
                 job['url'] or '尚无结果链接', '', job['body'], '']
    return '\n'.join(text)


def daily_summary(report):
    counts = report['today_submitted']
    if counts is None:
        return '今日数量未知，数据读取未完成。'
    registered = (report.get('counts') or {}).get('recorded', 0)
    return (f"今日收到平台回执：帖子 {counts.get('thread', 0)} 篇 · 评论 {counts.get('reply', 0)} 条。"
            f"最近记录另有网页发布登记 {registered} 条，未计入自动回执数。")


def html_report(report):
    e = html.escape
    issues = ''.join('<li>' + e(i['message']) + '</li>' for i in report['issues']) or '<li>当前未发现本地任务异常。</li>'
    cards = []
    summary = daily_summary(report)
    account_rows = ''.join('<li>' + e(a['name'] + '：' + a['status']) + '</li>' for a in report['accounts']) or '<li>暂无可读取的账号记录。</li>'
    for job in report['jobs']:
        link = '<a href="' + e(job['url'], quote=True) + '" target="_blank" rel="noopener noreferrer">查看平台结果</a>' if job['url'].startswith('https://') else '尚无结果链接'
        cards.append('<article><h3>' + e(job['title']) + '</h3><p>' + e(job['platform_name'] + ' · ' + (job['destination'] or '个人主页') + ' · ' + STATE_LABELS.get(job['state'], job['state'])) +
                     '</p><p>计划时间：' + local_time(job['due']) + '</p><p>' + e(job['message']) + '</p>' + link +
                     '<details><summary>完整内容</summary><pre>' + e(job['body']) + '</pre></details></article>')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JM 社区每日巡检</title><style>body{font:16px/1.7 system-ui;margin:40px auto;padding:0 24px;max-width:1000px;background:#f5f7f6;color:#243a35}a{color:#176d58}article,section{background:white;padding:22px;border-radius:12px;margin:18px 0}pre{white-space:pre-wrap;font:inherit}h1,h3{line-height:1.4}small{color:#65766f}</style>
<h1>JM 社区每日巡检</h1><p>''' + e(report['checked_at']) + ' · 北京时间 · ' + e(STATUS_LABELS[report['status']]) + '''</p>
<p><a href="http://127.0.0.1:8776/#community">打开 JM 工作台</a> · 每天 10:30 更新</p><small>''' + e(report['scope']) + '''</small>
<section><p>''' + e(summary) + '</p><ul>' + account_rows + '</ul></section><section><h2>需要处理</h2><ul>' + issues + '</ul></section><h2>帖子和评论</h2>' + ''.join(cards) + '</html>'


def run(port, output, now=None):
    now = time.time() if now is None else now
    output = Path(output)
    previous = read_json(output / 'state.json')
    report = analyse(collect(port), now)
    signature = change_signature(report)
    changed = signature != previous.get('signature')
    report['meaningful_change'] = changed
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    for name, content in [('latest.json', encoded), ('latest.md', markdown(report)), ('latest.html', html_report(report)),
                          (report['day'] + '.json', encoded)]:
        atomic_write(output / name, content)
    if changed:
        entry = {'checked_at': report['checked_at'], 'status': report['status'], 'issues': report['issues'],
                 'submitted': [j['id'] for j in report['jobs'] if j['state'] == 'submitted']}
        with (output / 'changes.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
    atomic_write(output / 'state.json', json.dumps({'signature': signature, 'checked_at': report['checked_at']}, ensure_ascii=False))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8776)
    parser.add_argument('--output', type=Path, default=ROOT / 'var' / 'community-monitor')
    args = parser.parse_args()
    run(args.port, args.output)
