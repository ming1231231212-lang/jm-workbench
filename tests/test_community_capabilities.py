import pytest
from fastapi.testclient import TestClient
from jm_workbench.web.app import create_app
from jm_workbench.community.models import CommunityAccount, CommunityPost, DailyPlan
from jm_workbench.community.registry import platform, safe_post_url


@pytest.mark.parametrize('pid',['weibo','wechat_mp'])
def test_web_platform_workflow_never_claims_or_attempts_automatic_publication(tmp_path,pid):
    class NoWrites:
        def publish(self,*args): raise AssertionError('web platform must never auto-submit')
        def check(self,*args): raise AssertionError('web platform has no automatic identity check')
        def open(self,a,url): return {'message':'opened','url':url}
    app=create_app(tmp_path,worker=False,community_adapter=NoWrites());s=app.state.community
    a=s.save_account(CommunityAccount(platform=pid,name='local draft account'))
    caps=platform(pid)['capabilities']
    assert caps['local_draft'] and caps['open_website'] and caps['record_link']
    assert not caps['auto_publish'] and not caps['auto_comment'] and not caps['daily_plan']
    p=s.save(CommunityPost(request_id='web-platform-draft',title='邀请大家一起建设趣造AI',body='趣造AI quzaoai.com，收集大家真正使用的AI工具。',targets=[{'account_id':a['id']}]))['id']
    s.launch(p);s.tick()
    job=s.jobs(p)[0];assert job['state']=='manual'
    assert s.open_job(job['id'])['url']==platform(pid)['compose']
    url='https://weibo.com/123456/Abc123' if pid=='weibo' else 'https://mp.weixin.qq.com/s/test_article'
    s.record_url(job['id'],url)
    assert s.jobs(p)[0]['state']=='recorded'
    with TestClient(app,base_url='http://127.0.0.1:8776') as client:
        result=client.get('/api/community/posts/'+p+'/export')
        assert result.status_code==200 and 'attachment' in result.headers['content-disposition']
        assert 'quzaoai.com' in result.text
    assert s.state()['summary']['thread_submitted']==0


def test_registry_does_not_infer_permission_from_a_website():
    assert platform('tieba')['capabilities']['auto_comment']
    assert not platform('wechat_mp')['automatic']
    with pytest.raises(ValueError):platform('unknown')
    with pytest.raises(ValueError):safe_post_url('wechat_mp','https://mp.weixin.qq.com.evil.test/s/abc')


def test_export_escapes_markup_and_missing_post_is_a_friendly_error(tmp_path):
    app=create_app(tmp_path,worker=False);s=app.state.community
    a=s.save_account(CommunityAccount(platform='wechat_mp',name='个人订阅号'))
    p=s.save(CommunityPost(request_id='escape-export-request',title='<script>bad</script>',body='<img src=x onerror=bad>\nhttps://quzaoai.com',targets=[{'account_id':a['id']}]))['id']
    with TestClient(app,base_url='http://127.0.0.1:8776') as c:
        r=c.get('/api/community/posts/'+p+'/export?format=html')
        assert r.status_code==200 and '<script>bad' not in r.text
        assert '&lt;img' in r.text and 'https://quzaoai.com' in r.text
        assert c.get('/api/community/posts/missing/export').status_code==400
        assert c.get('/api/community/posts/'+p+'/export?format=exe').status_code==422
