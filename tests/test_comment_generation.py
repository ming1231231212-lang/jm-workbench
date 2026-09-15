import pytest
from jm_workbench.core.models import TaskInput
from jm_workbench.policies.comments import ADULT_CORE, candidates, examples, variants
from jm_workbench.policies.rules import assess, assess_item, validate_template, detail_ready


def task(**changes):
    return dict(name='收货', platform='ks', kind='adult_comments', keywords=['成人用品店'],
                adult_target='merchant', comment_mode='core_variants', comment_core=ADULT_CORE, **changes)


@pytest.mark.parametrize('caption,ok', [
    ('本店成人用品今天正常营业', True),
    ('我们店情趣用品，记录一下开店日常', True),
    ('我开了一家成人用品店，今天开门了', True),
    ('我们经营着一家情趣用品店，欢迎了解', True),
    ('本店成人用品库存清仓', True),
    ('本店女装今天正常营业 #成人用品', False),
    ('今天开门了 #成人用品 #本店', False),
    ('成人用品店今天开门了', False),
    ('新闻报道，本店成人用品每天正常营业', False),
    ('本店成人用品加盟招商代理', False),
    ('今天探店本店成人用品，买家测评', False),
    ('朋友的店成人用品今天正常营业', False),
    ('不是我的店，成人用品今天开门了', False),
    ('本店成人用品怎么开，课程培训', False),
    ('我想开成人用品店，准备招人', False),
    ('本店成人用品无货，已经全部卖完了', False),
    ('本店鞋服正常营业，了解成人用品行业', False),
])
def test_merchant_scope_checks_business_and_ownership(caption, ok):
    assert assess('adult_comments', caption, 'merchant')[0] is ok


def test_legacy_inventory_scope_is_preserved():
    assert not assess('adult_comments', '本店成人用品正常营业')[0]
    assert assess('adult_comments', '本店成人用品补货')[0]
    assert not assess('adult_comments', '本店成人用品正常营业', 'anything')[0]


def test_nickname_query_comments_and_media_cannot_approve():
    assert not assess_item(task(), dict(caption='今天开门了', nickname='本店成人用品', source={'query':'成人用品店'}))[0]
    assert not assess_item(task(), dict(caption='本店成人用品正常营业', nickname='城市新闻'))[0]
    assert not assess_item(task(), dict(caption='本店成人用品正常营业', comment_id='comment1'))[0]


def test_core_variants_preserve_conditional_meaning_and_are_stable():
    pool = variants(ADULT_CORE)
    assert len(pool) > 3 and len(pool) == len(set(pool))
    for text in pool:
        validate_template('adult_comments', text)
        assert '积压' in text and '停卖' in text
        assert any(w in text for w in ('如果有', '要是有', '若有'))
        assert '我' in text
    texts = [candidates(task(), {'video_id': f'video{i:04d}'})[0] for i in range(50)]
    assert len(set(texts)) > 3
    item = dict(video_id='video1234', caption='本店成人用品正常营业')
    assert candidates(task(), item) == candidates(task(), dict(item, observed_at=99999999))
    assert len(candidates(task(), item)) == 1
    assert all(text in pool for text in examples(task()))


@pytest.mark.parametrize('core', [
    '店里如果有积压或停卖的货可以找我微信12345678哦',
    '你店里肯定有积压或停卖的货，赶快联系我',
    '店里如果有积压或停卖的货可以找我，招募陪玩',
    '店里如果有积压或停卖的货可以找我，保证高价回收',
])
def test_invalid_core_cannot_be_used(core):
    with pytest.raises(ValueError):
        TaskInput.model_validate(dict(task(), comment_core=core))


def test_old_task_configuration_keeps_its_template_and_scope():
    old = dict(name='旧任务',platform='ks',kind='adult_comments',keywords=['成人用品'],templates=[ADULT_CORE])
    parsed = TaskInput.model_validate(old).model_dump()
    assert parsed['adult_target'] == 'inventory'
    assert parsed['comment_mode'] == 'templates'
    assert candidates(parsed, {'video_id':'video1234'}) == [ADULT_CORE]


def test_merchant_detail_still_requires_permission_and_identity():
    item = dict(video_id='video1234', author_id='author1234', caption='本店成人用品正常营业',
                detail_verified=True, can_comment=True, source={'kind':'detail'})
    assert detail_ready('adult_comments', item, 'merchant')[0]
    assert not detail_ready('adult_comments', item, 'inventory')[0]
    assert not detail_ready('adult_comments', dict(item, can_comment=False), 'merchant')[0]
    assert not detail_ready('adult_comments', dict(item, detail_verified=False), 'merchant')[0]
