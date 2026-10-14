import json
from types import SimpleNamespace
import pytest
from jm_workbench.community.material_model import MaterialModel

def test_review_pairs_each_comment_with_its_own_original_not_new_article():
    captured=[]
    model=MaterialModel(SimpleNamespace(values={}),transport=lambda system,data:(captured.append(data) or {'approved':True,'reason':'对应原帖'}))
    source={'url':'https://tieba.baidu.com/p/123456','title':'AI用量怎么看','excerpt':'我的问题是查看具体的每日用量，并非整理会议记录。'}
    prepared={'article':{'title':'会议记录怎么核验','body':'独立文章'},'replies':[{'url':source['url'],'body':'能否导出每天的用量明细？'}]}
    model.review('tieba',prepared,[source])
    assert captured[0]['comments'][0]['original_post']==source
    assert '会议记录' not in captured[0]['comments'][0]['original_post']['title']

@pytest.mark.parametrize('change',[{'baseUrl':'https://untrusted.example/api'},{'models':[{'id':'paid-model'}]}])
def test_model_rejects_unverified_endpoint_or_paid_fallback(tmp_path,change):
    provider={'baseUrl':'https://openrouter.ai/api/v1','apiKey':'fixture-test-credential','models':[{'id':'nvidia/nemotron-3-super-120b-a12b:free'}],**change}
    config=tmp_path/'model.json';config.write_text(json.dumps({'models':{'providers':{'openrouter':provider}}}),encoding='utf-8')
    model=MaterialModel(SimpleNamespace(values={'community_model_config':str(config)}))
    with pytest.raises(ValueError):model.settings()

def test_missing_disclosure_and_link_are_added_without_overwriting_generated_body():
    original='比较两个工具时先定义同一份输入与核验条件。'
    model=MaterialModel(SimpleNamespace(values={}),transport=lambda *args:{'article':{'title':'比较AI工具的具体方法','body':original,'platform_tags':[]},'replies':[]})
    data=model.generate('juejin','2026-10-16',[],[],True,0,'本人维护趣造AI')
    assert data['article']['body'].startswith(original)
    assert 'quzaoai.com' in data['article']['body'] and 'AI辅助' in data['article']['body']
    assert 'https://' not in data['article']['body']
