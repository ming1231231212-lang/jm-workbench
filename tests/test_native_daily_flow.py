from datetime import datetime
from jm_workbench.web.app import create_app
from jm_workbench.core.config import Config
from jm_workbench.community.models import CommunityAccount,NativeBindInput,DailyPlan
from jm_workbench.community.service import SHANGHAI


def test_three_native_platform_plans_run_only_from_tomorrow_and_keep_six_unique_receipts(tmp_path):
    Config(tmp_path).save({'community_browser_execution':'native'})
    class Fake:
        sent=[]
        def check(self,a,secret):return a['native_binding']['identity']
        def publish(self,a,secret,p,target):
            self.sent.append((a['platform'],p['kind'],p['body'],target))
            url=target if p['kind']=='reply' else {'tieba':'https://tieba.baidu.com/p/123456789','juejin':'https://juejin.cn/post/1234567890123456','zhihu':'https://zhuanlan.zhihu.com/p/123456789'}[a['platform']]
            return {'post_id':'fixture','url':url,'visibility':'account_visible'}
    fake=Fake();s=create_app(tmp_path,worker=False,community_adapter=fake).state.community
    now=[datetime(2026,10,14,13,0,tzinfo=SHANGHAI).timestamp()];s.clock=lambda:now[0]
    plans=[]
    for platform,identity,profile,board in [
        ('tieba','tieba:tb.fixture','https://tieba.baidu.com/home/main?id=tb.fixture','ai工具'),
        ('juejin','1234567890123456','https://juejin.cn/user/1234567890123456','人工智能'),
        ('zhihu','zhihu:fixture','https://www.zhihu.com/people/fixture',''),
    ]:
        a=s.save_account(CommunityAccount(name='fixture '+platform,platform=platform))
        a=s.bind_native(a['id'],NativeBindInput(version=a['version'],identity=identity,name='fixture',profile_url=profile))['account']
        prefix={'tieba':'https://tieba.baidu.com/p/','juejin':'https://juejin.cn/post/','zhihu':'https://zhuanlan.zhihu.com/p/'}[platform]
        replies=[{'url':prefix+str(1234567890123456+i),'title':'原帖具体讨论'+str(i),'excerpt':'这里是原帖关于保存来源和输出边界的完整具体内容，帮助核验实际目标。','body':'针对第'+str(i)+'个原帖的独立建议，先约定输入与输出，再检查未知信息与来源依据。（AI辅助整理）'} for i in range(5)]
        body='说明：本文使用AI辅助整理。这是隔离模拟测试所用的独立任务说明，不会提交到任何真实平台。'+'核验要保留输入、输出和原文依据，并明确未验证的范围。'*8
        p=s.daily.save(DailyPlan(name='fixture '+platform,account_id=a['id'],board=board,start_date='2026-10-15',rules_note='只使用核对过的具体原帖，每篇帖子和评论不重复。',topics=[{'title':'本地模拟文章内容验收','body':body,'platform_tags':['人工智能']}],replies=replies))['id']
        s.daily.control(p,'enable');s.daily.prepare(p,force=True);plans.append(p)
    assert not s.state()['posts'] and not fake.sent
    now[0]=datetime(2026,10,15,10,0,tzinfo=SHANGHAI).timestamp()
    for _ in range(20):s.tick();now[0]+=1801
    assert len(fake.sent)==18
    for platform in ('tieba','juejin','zhihu'):
        rows=[x for x in fake.sent if x[0]==platform]
        assert sum(x[1]=='thread' for x in rows)==1 and sum(x[1]=='reply' for x in rows)==5
        assert len({x[2] for x in rows})==6
    assert all(j['state']=='submitted' and j['receipt']['visibility']=='account_visible' for p in s.state()['posts'] for j in p['jobs'])
    for p in plans:s.daily.control(p,'pause')
    now[0]+=86400;s.tick();assert len(fake.sent)==18


def test_native_desktop_lock_serializes_other_operations(tmp_path):
    import os,pytest
    from jm_workbench.community.native_runtime import desktop_lock
    from jm_workbench.community.adapters import RetryablePreflight
    if os.name!='nt':pytest.skip('Windows native file lock')
    with desktop_lock(tmp_path):
        with pytest.raises(RetryablePreflight):
            with desktop_lock(tmp_path):pass
    with desktop_lock(tmp_path):pass
