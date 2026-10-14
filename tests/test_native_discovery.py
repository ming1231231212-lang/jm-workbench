from datetime import datetime
import pytest
from jm_workbench.community.native_discovery import activity,list_candidates,original,TZ,NativeDiscovery

def test_dates_do_not_make_last_year_new_or_invent_activity():
    now=datetime(2026,1,2,tzinfo=TZ).timestamp()
    assert datetime.fromtimestamp(activity('12-31',now)[0],TZ).year==2025
    assert activity('赞同 999',now)==(0,'')
    assert activity('回复于3小时前',now)[0]==now-10800

def test_card_evidence_uses_own_ancestor_not_sidebar():
    s={'url':'https://www.zhihu.com/search?type=content&q=AI','nodes':[
      {'key':'doc','type':'Document','name':'2026-10-15 热搜 9999','parent':''},
      {'key':'card','type':'ListItem','name':'AI工具具体话题 赞同 3 2小时前','parent':'doc'},
      {'key':'link','type':'Hyperlink','name':'AI工具具体话题','value':'https://zhuanlan.zhihu.com/p/12345678','parent':'card'}]}
    r=list_candidates(s,'zhihu',1800000000)[0]
    assert r['activity_evidence']=='2小时前' and r['heat']==3

def test_original_cannot_be_search_snippet_or_different_destination():
    candidate={'url':'https://tieba.baidu.com/p/1234567','activity_at':1800000000,'activity_evidence':'1小时前'}
    s={'url':candidate['url'],'text':'具体讨论AI工作流\n'+('保存输入、原文与实际输出，区分已核验事实和推测。'*4)+'\n转发\n评论中的虚假信息不要读',
       'nodes':[{'type':'Document','name':'具体讨论AI工作流-百度贴吧'}]}
    r=original(s,'tieba',candidate,1800000000)
    assert '虚假信息' not in r['excerpt'] and r['title']=='具体讨论AI工作流'
    s['url']='https://tieba.baidu.com/p/9876543'
    with pytest.raises(ValueError):original(s,'tieba',candidate,1800000000)

def test_wrong_search_query_is_rejected_even_on_same_route():
    class UI:
        def call(self,action,**args):return {'url':'https://www.zhihu.com/search?q=unrelated','text':'x'*500}
    with pytest.raises(Exception,match='尚未完整'):NativeDiscovery(UI(),sleep=lambda _:None).read('https://www.zhihu.com/search?q=AI')
