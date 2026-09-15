import pytest
from jm_workbench.policies.rules import assess_item, detail_ready


def task(keyword='成人用品店怎么样'):
    return dict(kind='adult_comments', adult_target='keyword', keywords=[keyword])


def search(caption, keyword='成人用品店怎么样', **extra):
    return dict(video_id='video1234', author_id='author1234', caption=caption,
                source={'kind':'search','query':keyword}, **extra)


@pytest.mark.parametrize('caption,ok', [
    ('成人用品店今天正常营业', True),
    ('记者调查：开成人用品店，加盟商称营业额低', True),
    ('如何开一家情趣用品店，分享创业经验', True),
    ('朋友的成人用品店最近开业了', True),
    ('买家测评情趣用品店服务，看看怎么样', True),
    ('新闻：成人用品店被盗，店主表示会继续经营', True),
    ('海口居民楼开设情趣用品外卖仓，引发讨论', True),
    ('今天去旅游路过成人用品店', False),
    ('成人用品店旁边女装店的新衣服', False),
    ('这不是成人用品店，我们只卖其他东西', False),
    ('今天开门了 #成人用品店', False),
    ('#成人用品店 #开店日常', False),
    ('这个产品有商机，适合开店', False),
    ('……', False),
    ('普通人如何创业，做实体店怎么样', False),
    ('幼态成人用品店 #儿童款', False),
])
def test_keyword_scope_uses_topic_not_store_ownership(caption, ok):
    assert assess_item(task(), search(caption))[0] is ok


def test_keyword_qualifiers_and_synonyms_are_checked():
    assert assess_item(task('情趣用品店'),search('成人用品店的开店经验','情趣用品店'))[0]
    assert assess_item(task('成人用品清仓'),search('情趣用品尾货库存处理','成人用品清仓'))[0]
    assert not assess_item(task('成人用品清仓'),search('成人用品店正常营业','成人用品清仓'))[0]
    assert not assess_item(task('成人用品店'),search('成人用品的产品说明','成人用品店'))[0]
    assert not assess_item(task('成人用品店'),search('成人用品店开门了','另一关键词'))[0]
    assert not assess_item(task(),dict(search('成人用品店开门了'),source={'kind':'recommendation','query':'成人用品店怎么样'}))[0]


def test_search_detail_provenance_must_bind_video_and_configured_keyword():
    item=search('记者调查：成人用品店如何经营')
    item.update(source={'kind':'detail'},detail_verified=True,can_comment=True)
    assert not detail_ready('adult_comments',item,'keyword',task()['keywords'])[0]
    item['search_origin']={'kind':'search','video_id':'video1234','query':'成人用品店怎么样'}
    assert detail_ready('adult_comments',item,'keyword',task()['keywords'])[0]
    item['search_origin']['video_id']='other-video'
    assert not detail_ready('adult_comments',item,'keyword',task()['keywords'])[0]
    item['search_origin']['video_id']='video1234'
    assert not detail_ready('adult_comments',item,'keyword',['情趣用品店'])[0]
    item['can_comment']=False
    assert not detail_ready('adult_comments',item,'keyword',task()['keywords'])[0]


def test_media_allowed_but_names_keywords_and_comments_are_not_content():
    assert assess_item(task(),search('记者调查成人用品店的经营情况',nickname='城市新闻'))[0]
    assert not assess_item(task(),search('今天开门了',nickname='成人用品店'))[0]
    assert not assess_item(task(),search('成人用品店开门了',comment_id='comment123'))[0]
