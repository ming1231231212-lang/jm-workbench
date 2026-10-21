import json
from types import SimpleNamespace
import pytest
import io
import urllib.error
from jm_workbench.community.material_model import MaterialModel

def wire_model(tmp_path,monkeypatch,responses):
    path=tmp_path/'model.json'
    path.write_text(json.dumps({'models':{'providers':{'openrouter':{
        'baseUrl':'https://openrouter.ai/api/v1','apiKey':'test-only-key',
        'models':[{'id':'primary:free'}]}}}}))
    calls=[]
    def request(req,**kwargs):
        payload=json.loads(req.data);calls.append(payload)
        value=responses.pop(0)
        if isinstance(value,int):raise urllib.error.HTTPError(req.full_url,value,'fixture',{},None)
        return io.BytesIO(json.dumps({'model':'actual:free','usage':{'cost':0},'choices':[
            {'finish_reason':'stop','message':{'content':json.dumps(value)}}]}).encode())
    monkeypatch.setattr('urllib.request.urlopen',request)
    return MaterialModel(SimpleNamespace(values={'community_model_config':str(path),'community_model_name':'primary:free'})),calls

def test_unavailable_model_uses_only_free_router_and_reuses_working_route(tmp_path,monkeypatch):
    m,calls=wire_model(tmp_path,monkeypatch,[404,{'article':{}},{'approved':True}])
    assert m.call('generate',{})=={'article':{}}
    assert m.call('review',{})=={'approved':True}
    assert [p['model'] for p in calls]==['primary:free','openrouter/free','openrouter/free']
    assert m.last_call['model']=='actual:free'

@pytest.mark.parametrize('status',[401,403])
def test_auth_or_access_denial_does_not_switch_route(tmp_path,monkeypatch,status):
    m,calls=wire_model(tmp_path,monkeypatch,[status])
    with pytest.raises(ValueError,match=str(status)):m.call('generate',{})
    assert len(calls)==1

def test_all_free_routes_failed_retains_codes_and_stops_bounded(tmp_path,monkeypatch):
    m,calls=wire_model(tmp_path,monkeypatch,[404,503])
    with pytest.raises(ValueError,match='404.*503'):m.call('generate',{})
    assert len(calls)==2

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

def test_posts_only_prompt_excludes_comment_instructions_and_limits_history():
    captured=[]
    m=MaterialModel(SimpleNamespace(values={}),transport=lambda system,data:(captured.append((system,data)) or {'article':{'title':'核对材料','body':'核对来源'},'replies':[]}))
    m.generate('zhihu','2026-10-21',[],['历史文章'*500]*70,True,0,'已核实事实')
    instruction,data=captured[0]
    assert '不写评论' in instruction and 'anchor必须' not in instruction
    assert len(data['history'])<=20 and all(len(x)<=360 for x in data['history'])
    assert data['need_article'] is True

def test_posts_only_extracts_article_fields_and_never_accepts_generated_comments():
    raw={'article':{'title':'核对输入资料的来源','body':'只调整资料结构，不补造事实。'*30,
        'replies':[],'platform_tags':['人工智能'],'publish':True},'replies':[{'body':'unexpected'}]}
    m=MaterialModel(SimpleNamespace(values={}),transport=lambda *args:raw)
    out=m.generate('zhihu','2026-10-21',[],[],True,0,'已核实事实')
    assert set(out['article'])=={'title','body','platform_tags'}
    assert out['replies']==[] and out['article']['body'].startswith('只调整资料结构')

def test_only_quality_approved_free_model_can_be_preferred(tmp_path,monkeypatch):
    m,calls=wire_model(tmp_path,monkeypatch,[{'approved':True}])
    with pytest.raises(ValueError):m.prefer_free_model('paid-model')
    m.prefer_free_model('quality-checked:free')
    assert m.call('review',{})=={'approved':True}
    assert calls[0]['model']=='quality-checked:free'

@pytest.mark.parametrize('suffix',['（AI辅助整理）','(AI辅助整理)'])
def test_approved_url_is_separated_from_disclosure_before_link_validation(suffix):
    from jm_workbench.community.material_quality import validate_generated
    body='对照原始输入检查每一项输出，未在原文出现的信息单独标记，不补成确定事实。'*9
    m=MaterialModel(SimpleNamespace(values={}),transport=lambda *args:{'article':{
        'title':'核对输入和输出中的事实','body':body+'https://quzaoai.com/'+suffix,'platform_tags':['人工智能']},'replies':[]})
    out=m.generate('zhihu','2026-10-21',[],[],True,0,'已核实事实')
    assert 'https://quzaoai.com/\n'+suffix in out['article']['body']
    assert validate_generated(out,'zhihu',[],[],set(),True)['article']

@pytest.mark.parametrize('url',['https://quzaoai.com/secret','https://quzaoai.com.evil.example/','https://other.example/'])
def test_disclosure_formatting_does_not_allow_other_urls(url):
    from jm_workbench.community.material_quality import validate_generated
    body='核对原始输入中的具体条件，逐项比较输出是否准确，保留来源与不确定内容。'*10
    m=MaterialModel(SimpleNamespace(values={}),transport=lambda *args:{'article':{
        'title':'核对输出中的关键条件','body':body+url+'（AI辅助整理）','platform_tags':['人工智能']},'replies':[]})
    out=m.generate('zhihu','2026-10-21',[],[],True,0,'已核实事实')
    with pytest.raises(ValueError,match='未授权链接'):validate_generated(out,'zhihu',[],[],set(),True)


@pytest.mark.parametrize('platform,expected',[('juejin',['人工智能']),('zhihu',['人工智能','AI工具'])])
def test_generated_tags_use_platform_verified_options(platform,expected):
    model=MaterialModel(SimpleNamespace(values={}),transport=lambda *args:{'article':{
        'title':'如何核对AI翻译','body':'用原文核对人名和数字。','platform_tags':['人工智能','AI工具']},'replies':[]})
    data=model.generate(platform,'2026-10-16',[],[],True,0,'本人维护趣造AI')
    assert data['article']['platform_tags']==expected and data['replies']==[]
