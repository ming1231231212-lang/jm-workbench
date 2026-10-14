import pytest
from jm_workbench.community.material_quality import validate_generated,similar,rank_candidates

def candidate(i=1):
    return {'url':'https://juejin.cn/post/'+str(1234567890123456+i),'title':'AI会议纪要怎样核验行动项',
      'excerpt':'会议纪要需要区分建议和已经作出的决定。每条行动项保留录音时间点，责任人没有说清楚时标为待确认。',
      'observed_at':1791943200,'activity_at':1791940000,'activity_evidence':'2小时前','heat':12,'heat_evidence':'12点赞'}

def generated():
    return {'article':None,'replies':[{'source_url':candidate()['url'],'anchor':'每条行动项保留录音时间点',
      'body':'行动项建议按录音时间点复核，把讨论中的建议和最后确定的决定放在不同列，负责人没有明确就留待确认，后续追踪更方便。（AI辅助整理）'}]}

def test_reply_must_use_real_original_anchor_and_keeps_source():
    result=validate_generated(generated(),'juejin',[candidate()],[],[],False)
    assert result['replies'][0]['url']==candidate()['url']
    assert result['replies'][0]['excerpt']==candidate()['excerpt']

@pytest.mark.parametrize('change',[{'source_url':'https://juejin.cn/post/9999999999999999'}, {'anchor':'不存在的观点不能作为原文依据'}, {'body':'这个工具不错，欢迎到quzaoai.com注册使用，私信我了解详情。（AI辅助整理）'}])
def test_untrusted_url_hallucinated_anchor_or_advertising_is_rejected(change):
    d=generated();d['replies'][0].update(change)
    with pytest.raises(ValueError):validate_generated(d,'juejin',[candidate()],[],[],False)

def test_repeated_target_or_near_identical_body_is_rejected():
    d=generated()
    with pytest.raises(ValueError):validate_generated(d,'juejin',[candidate()],[],[candidate()['url']],False)
    with pytest.raises(ValueError):validate_generated(d,'juejin',[candidate()],[d['replies'][0]['body'].replace('更方便','更容易')],[],False)

def test_hotness_must_have_evidence_and_relevance_is_required():
    c=candidate();bad={**c,'url':'https://juejin.cn/post/1234567890123459','title':'周末去哪里玩','excerpt':'今天去公园赏花，天气很好，公园里的游人非常多。'}
    stale={**c,'activity_at':0,'activity_evidence':'','heat':999,'heat_evidence':''}
    assert rank_candidates([bad,stale,c],['AI','会议纪要'],1791943200)==[c]

def test_punctuation_or_ai_disclosure_does_not_defeat_similarity():
    assert similar('先核对录音里的责任人，再确认截止日期。（AI辅助整理）','先核对录音里的责任人，再确认截止日期！')

def test_one_bad_generated_comment_does_not_discard_other_valid_material():
    from jm_workbench.community.materials import validate_batch
    d=generated();d['replies'].append({'source_url':candidate(2)['url'],'anchor':'不在原帖中的虚构内容','body':'没有真实依据的泛泛回复，不应该进入发送队列，即使它看起来很长。（AI辅助整理）'})
    prepared,issues=validate_batch(d,'juejin',[candidate(),candidate(2)],[],[],False)
    assert len(prepared['replies'])==1 and issues
    assert prepared['replies'][0]['url']==candidate()['url']
