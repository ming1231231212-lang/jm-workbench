"""Zhihu handoff tests: no credentials, remote requests, or real publications."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from jm_workbench.community.models import CommunityAccount, CommunityPost, DailyPlan
from jm_workbench.community.registry import compose_url, platform, thread_url
from jm_workbench.web.app import create_app

ARTICLE = 'https://zhuanlan.zhihu.com/p/624717941'
ANSWER = 'https://www.zhihu.com/question/123456/answer/654321'


class WebOnly:
    def __init__(self): self.opened = []
    def check(self, *args): raise AssertionError('must not probe an automatic connection')
    def publish(self, *args): raise AssertionError('must not publish to a website')
    def ensure_connection(self, *args): raise AssertionError('must not install or connect an extension')
    def open(self, account, url):
        self.opened.append(url)
        return {'url': url, 'message': 'local Chrome handoff'}


@pytest.fixture
def ctx(tmp_path):
    adapter = WebOnly()
    app = create_app(tmp_path, worker=False, community_adapter=adapter)
    s = app.state.community
    a = s.save_account(CommunityAccount(platform='zhihu', name='知乎测试账号'))
    return app, s, a, adapter


def draft(s, a, ident='zhihu-reply-fixture', target=ARTICLE, body='针对原帖的具体问题，提供可复现的小样本与核对方法。', kind='reply'):
    return s.save(CommunityPost(request_id=ident, kind=kind, title='知乎流程测试', body=body,
        source_title='原始技术讨论' if kind == 'reply' else '',
        targets=[{'account_id': a['id'], 'destination': target if kind == 'reply' else ''}]))['id']


def test_capabilities_separate_web_comment_from_automatic_execution(ctx):
    _, s, a, _ = ctx
    p = next(p for p in s.state()['platforms'] if p['id'] == 'zhihu')
    assert p['capabilities']['comment_draft'] and p['capabilities']['web_comment']
    assert not p['automatic'] and not p['capabilities']['auto_comment'] and not p['capabilities']['daily_plan']
    assert s.account(a['id'])['automatic_execution'] is False
    with pytest.raises(ValueError, match='网页发布'): s.check_account(a['id'])


@pytest.mark.parametrize('url,expected', [
    (ARTICLE + '?utm_source=share#comments', ARTICLE),
    (ANSWER + '?commentId=123#comment', ANSWER),
])
def test_comment_urls_are_canonical_and_open_the_original_post(url, expected):
    assert thread_url('zhihu', url) == expected
    assert compose_url('zhihu', expected) == expected
    assert compose_url('zhihu') == 'https://zhuanlan.zhihu.com/write'


@pytest.mark.parametrize('url', [
    'http://zhuanlan.zhihu.com/p/624717941',
    'https://zhuanlan.zhihu.com.evil.example/p/624717941',
    'https://user@zhuanlan.zhihu.com/p/624717941',
    'https://zhuanlan.zhihu.com:444/p/624717941',
    'https://zhuanlan.zhihu.com/write',
    'https://www.zhihu.com/signin',
    'https://www.zhihu.com/people/example',
    'https://www.zhihu.com/question/123456',
    'https://www.zhihu.com/question/123456/answer/0',
    'https://zhuanlan.zhihu.com/p/%36%32%34%37%31%37%39%34%31',
])
def test_comment_target_rejects_non_content_and_ambiguous_links(url):
    with pytest.raises(ValueError, match='知乎'): thread_url('zhihu', url)


@pytest.mark.parametrize('target', [ARTICLE, ANSWER])
def test_complete_comment_handoff_retains_content_target_and_truthful_receipt(ctx, target):
    app, s, a, adapter = ctx
    post = draft(s, a, target=target)
    s.launch(post); s.tick()
    job = s.jobs(post)[0]
    assert job['state'] == 'manual' and job['started'] == 0
    assert s.open_job(job['id'])['url'] == target
    assert adapter.opened == [target]
    assert '针对原帖' in s.export_content(post)
    with TestClient(app, base_url='http://127.0.0.1:8776') as client:
        client.headers['X-JM-Token'] = client.get('/api/state').json()['token']
        res = client.post('/api/community/jobs/' + job['id'] + '/record', json={'url': target + '?share=1'})
        assert res.status_code == 200, res.text
    result = s.jobs(post)[0]
    assert result['state'] == 'recorded' and result['receipt']['url'] == target
    assert result['receipt']['visibility'] == 'user_reported'
    assert s.state()['summary']['reply_submitted'] == 0


def test_article_opens_editor_and_only_accepts_a_published_article_link(ctx):
    _, s, a, adapter = ctx
    post = draft(s, a, kind='thread'); s.launch(post)
    job = s.jobs(post)[0]
    assert s.open_job(job['id'])['url'] == 'https://zhuanlan.zhihu.com/write'
    assert adapter.opened == ['https://zhuanlan.zhihu.com/write']
    for bad in ('https://zhuanlan.zhihu.com/write', 'https://www.zhihu.com/people/example', ANSWER):
        with pytest.raises(ValueError, match='文章'): s.record_url(job['id'], bad)
    assert s.jobs(post)[0]['state'] == 'manual'
    s.record_url(job['id'], ARTICLE)
    assert s.jobs(post)[0]['state'] == 'recorded'


def test_comment_cannot_be_registered_under_a_different_post(ctx):
    _, s, a, _ = ctx
    post = draft(s, a); s.launch(post); job = s.jobs(post)[0]
    with pytest.raises(ValueError, match='原帖'): s.record_url(job['id'], 'https://zhuanlan.zhihu.com/p/624717942')
    assert s.jobs(post)[0]['state'] == 'manual'


def test_same_target_even_with_different_text_or_tracking_is_not_reserved_twice(ctx):
    _, s, a, _ = ctx
    first = draft(s, a); s.launch(first)
    other = draft(s, a, 'zhihu-second-fixture', ARTICLE + '?utm_source=other', '第二份不同的评论内容，也不应在同一个原帖重复创建任务。')
    with pytest.raises(ValueError, match='重复'): s.launch(other)
    assert not s.jobs(other)


def test_answer_id_alias_does_not_allow_repeated_comment(ctx):
    _, s, a, _ = ctx
    s.launch(draft(s, a, target=ANSWER))
    other = draft(s, a, 'zhihu-answer-alias', ANSWER.replace('/123456/', '/999999/'), '不同的路径和不同文案，仍然对应同一个回答标识，不应再次占用。')
    with pytest.raises(ValueError, match='重复'): s.launch(other)


def test_same_comment_body_cannot_be_reused_under_a_different_post(ctx):
    _, s, a, _ = ctx
    s.launch(draft(s, a))
    other = draft(s, a, 'zhihu-content-duplicate', ARTICLE.replace('624717941', '624717942'))
    with pytest.raises(ValueError, match='重复'): s.launch(other)


def test_uncertain_result_resolution_cannot_bypass_original_target_validation(ctx):
    _, s, a, _ = ctx
    post = draft(s, a); s.launch(post); job = s.jobs(post)[0]
    with s.store.connect(True) as db: db.execute("UPDATE community_jobs SET state='unknown' WHERE id=?", (job['id'],))
    with pytest.raises(ValueError, match='原帖'):
        s.resolve(job['id'], 'submitted', '隔离测试核对说明，结果链接必须属于原帖。', ARTICLE.replace('624717941', '624717942'))
    assert s.jobs(post)[0]['state'] == 'unknown'


def test_concurrent_reservation_only_creates_one_manual_job(ctx):
    _, s, a, _ = ctx
    posts = [draft(s, a, 'zhihu-concurrent-' + str(i)) for i in range(3)]
    def launch(post):
        try: s.launch(post); return True
        except ValueError: return False
    with ThreadPoolExecutor(max_workers=3) as pool: assert sum(pool.map(launch, posts)) == 1


def test_platform_pause_and_unsupported_daily_plan_are_preserved(ctx):
    _, s, a, _ = ctx
    with s.store.connect(True) as db: db.execute("INSERT INTO community_risk VALUES('zhihu','fixture restriction',1)")
    with pytest.raises(ValueError, match='暂停'): s.launch(draft(s, a))
    with pytest.raises(ValueError): s.daily.save(DailyPlan(name='知乎计划', account_id=a['id'], board='人工智能', rules_note='仅核对本地能力，不应启用未接入的每日自动发布'))
    assert s.state()['risk'][0]['platform'] == 'zhihu'


def test_long_comment_is_rejected_before_task_creation(ctx):
    _, s, a, _ = ctx
    post = draft(s, a, body='字' * 2001)
    with pytest.raises(ValueError, match='2000'): s.launch(post)
    assert not s.jobs(post)
