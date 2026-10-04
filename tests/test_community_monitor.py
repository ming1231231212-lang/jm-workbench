import copy
import json
from datetime import datetime
from unittest.mock import patch

from scripts import community_monitor as monitor


NOW = datetime(2026, 10, 4, 10, 30, tzinfo=monitor.SHANGHAI).timestamp()


def sample():
    return {'health': {'ok': True}, 'community': {'worker': True, 'platforms': [{'id': 'tieba', 'automatic': True}],
            'accounts': [{'id': 'test', 'name': 'Test', 'platform': 'tieba', 'enabled': True,
                          'identity': 'private', 'checked': NOW, 'secret': 'must-not-export'}],
            'risk': [], 'plans': [], 'posts': []}}


def add_job(raw, ident='one', state='submitted', body='useful answer', kind='reply', **kwargs):
    raw['community']['posts'].append({'id': 'post-' + ident, 'payload': {'title': 'Test title', 'body': body, 'kind': kind},
        'jobs': [{'id': ident, 'state': state, 'platform': 'tieba', 'account_id': 'test', 'identity': 'private',
                  'destination': 'https://tieba.baidu.com/p/12345', 'started': NOW - 60 if state == 'submitted' else 0,
                  'due': NOW + 600, 'updated': NOW, 'receipt': {'url': '', 'visibility': 'unverified'}, **kwargs}]})


def test_offline_counts_are_unknown_not_zero():
    result = monitor.analyse({'health': None, 'community': None}, NOW)
    assert result['status'] == 'error'
    assert result['counts'] is None and result['today_submitted'] is None
    assert not result['data_available']


def test_collect_only_two_read_requests_and_ignores_system_proxy():
    calls = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"worker": true}'
    class Opener:
        def open(self, req, timeout):
            calls.append((req.get_method(), req.full_url))
            return Response()
    with patch.object(monitor.urllib.request, 'build_opener', return_value=Opener()) as factory:
        monitor.collect()
    assert calls == [('GET', 'http://127.0.0.1:8776/api/health'), ('GET', 'http://127.0.0.1:8776/api/community/state')]
    assert factory.call_args.args[0].proxies == {}


def test_wrong_service_and_malformed_response_are_unknown():
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"app_id": "different-app", "posts": "wrong-type"}'
    class Opener:
        def open(self, *args, **kwargs): return Response()
    with patch.object(monitor.urllib.request, 'build_opener', return_value=Opener()):
        result = monitor.collect()
    assert result['health'] is None and result['community'] is None
    assert result['health_error'] == 'ValueError'


def test_expired_account_is_unknown_without_exposing_credentials():
    raw = sample()
    raw['community']['accounts'][0]['checked'] = NOW - 86401
    result = monitor.analyse(raw, NOW)
    encoded = json.dumps(result)
    assert result['status'] == 'warning'
    assert 'must-not-export' not in encoded and 'private' not in encoded


def test_receipt_does_not_become_public_visibility():
    raw = sample(); add_job(raw)
    result = monitor.analyse(raw, NOW)
    assert result['today_submitted'] == {'reply': 1}
    assert result['jobs'][0]['visibility'] == 'unverified'
    assert '公开可见' in result['scope'] and '未核验' in result['scope']


def test_shanghai_day_boundary():
    raw = sample()
    midnight = datetime(2026, 10, 4, tzinfo=monitor.SHANGHAI).timestamp()
    add_job(raw, started=midnight - 1)
    add_job(raw, 'two', body='another answer', started=midnight, destination='different')
    assert monitor.analyse(raw, NOW)['today_submitted'] == {'reply': 1}


def test_duplicate_content_and_target_reported_independently():
    raw = sample(); add_job(raw, body='Ａ useful answer!')
    add_job(raw, 'two', body='a useful answer')
    keys = [i['key'] for i in monitor.analyse(raw, NOW)['issues']]
    assert 'duplicate-content:two' in keys and 'duplicate-target:two' in keys


def test_different_accounts_and_cancelled_jobs_not_counted_as_duplicate():
    raw = sample(); add_job(raw)
    add_job(raw, 'two', identity='other')
    add_job(raw, 'three', state='cancelled')
    assert not monitor.analyse(raw, NOW)['issues']


def test_respect_user_pause_and_keep_input_unchanged():
    raw = sample(); add_job(raw, state='paused', message='用户暂停')
    raw['community']['plans'] = [{'id': 'plan', 'state': 'paused', 'message': '用户停止全部任务', 'payload': {'name': 'Plan'}}]
    before = copy.deepcopy(raw)
    assert monitor.analyse(raw, NOW)['status'] == 'ok'
    assert raw == before


def test_due_budget_wait_is_not_an_error_but_stalled_job_is():
    raw = sample(); add_job(raw, state='queued')
    assert monitor.analyse(raw, NOW)['status'] == 'ok'
    raw['community']['posts'][0]['jobs'][0]['due'] = NOW - 901
    assert monitor.analyse(raw, NOW)['status'] == 'warning'


def test_platform_risk_and_unknown_receipt_do_not_get_retried():
    raw = sample(); add_job(raw, state='unknown', message='结果不明，禁止重发')
    raw['community']['risk'] = [{'platform': 'tieba', 'reason': 'platform lock'}]
    result = monitor.analyse(raw, NOW)
    assert result['status'] == 'error'
    assert len(result['issues']) == 2 and result['jobs'][0]['state'] == 'unknown'


def test_html_escapes_content_and_rejects_non_https_result_link():
    raw = sample(); add_job(raw, body='<script>alert(1)</script>', receipt={'url': 'javascript:alert(1)'})
    rendered = monitor.html_report(monitor.analyse(raw, NOW))
    assert '<script>' not in rendered and '&lt;script&gt;' in rendered
    assert 'href="javascript:' not in rendered


def test_daily_report_and_change_log_are_idempotent(tmp_path):
    raw = sample(); add_job(raw)
    with patch.object(monitor, 'collect', return_value=raw):
        first = monitor.run(8776, tmp_path, NOW)
        second = monitor.run(8776, tmp_path, NOW + 2)
    assert first['meaningful_change'] and not second['meaningful_change']
    assert len((tmp_path / 'changes.jsonl').read_text(encoding='utf-8').splitlines()) == 1
    assert (tmp_path / '2026-10-04.json').is_file()
    assert not list(tmp_path.glob('*.tmp'))


def test_new_submission_is_a_meaningful_change():
    raw = sample(); add_job(raw, state='queued')
    before = monitor.change_signature(monitor.analyse(raw, NOW))
    raw['community']['posts'][0]['jobs'][0]['state'] = 'submitted'
    assert monitor.change_signature(monitor.analyse(raw, NOW)) != before


def test_draft_is_visible_but_never_counted_as_submitted():
    raw = sample()
    raw['community']['posts'] = [{'id': 'draft', 'state': 'draft', 'updated': NOW, 'jobs': [],
        'payload': {'title': 'Draft', 'body': 'Not sent', 'targets': [{'account_id': 'test', 'destination': 'board'}]}}]
    result = monitor.analyse(raw, NOW)
    assert result['counts'] == {'draft': 1}
    assert result['today_submitted'] == {}
    assert result['jobs'][0]['visibility'] == 'not_submitted'
    assert 'JM草稿' in monitor.html_report(result)


def test_web_link_registration_shown_separately_from_platform_receipts():
    raw = sample()
    raw['community']['platforms'][0]['name'] = '百度贴吧'
    add_job(raw, state='recorded', receipt={'url': 'https://tieba.baidu.com/p/12345', 'visibility': 'user_reported'})
    result = monitor.analyse(raw, NOW)
    assert result['today_submitted'] == {}
    rendered = monitor.html_report(result)
    assert '帖子 0 篇' in rendered and '网页发布登记 1 条' in rendered
    assert '百度贴吧' in rendered and '已登记链接 · 未核验公开可见' in rendered
