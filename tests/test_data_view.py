import time
import pytest
from jm_workbench.core.db import Store
from jm_workbench.policies.rules import DEFAULTS
from jm_workbench.services.data_view import classify, data_view

@pytest.fixture
def store(tmp_path):
    s=Store(tmp_path/'jm.db')
    for kind, cfg in DEFAULTS.items():
        s.put('task', dict(cfg, kind=kind, platform='ks', enabled=True, start_hour=20, end_hour=23))
    return s

def add(store, vid, caption, name='', run='batch1', **extra):
    store.add_evidence(run,'ks',dict(video_id=vid,author_id='author1234',caption=caption,nickname=name,**extra),'skipped','原执行判断')

def test_latest_batch_and_duplicates_are_explained(store):
    add(store,'oldvideo123','旧数据',run='legacy')
    add(store,'newvideo123','#实体店','某成人用品店',source={'query':'关键词一'})
    add(store,'newvideo123','#实体店','某成人用品店',source={'query':'关键词二'})
    result=data_view(store,batch='latest')
    assert result['summary']['records']==2
    assert result['summary']['unique']==1 and result['summary']['duplicates']==1
    assert result['summary']['content_matches']==0
    row=result['items'][0]
    assert set(row['keywords'])=={'关键词一','关键词二'}
    assert row['category']=='merchant' and row['comment_preview']['label']=='不会评论'
    assert data_view(store,batch='all')['summary']['unique']==2

@pytest.mark.parametrize('caption,name,category',[
    ('本店成人用品库存积压，需要清仓','某店','inventory'),
    ('#玉田同城 #实体店 #诚信经营','某成人店','merchant'),
    ('#开店日常 #老板娘日常 一直被模仿','未知品类店铺','merchant'),
    (' @品牌旗舰店(O123) 的精彩视频','某品牌旗舰店','merchant'),
    ('男子加盟成人用品店，负责人承诺回本','某媒体','discussion'),
    ('成人用品店被盗','某新闻频道','discussion'),
    ('本人22岁想做陪玩，求职','某人','jobseeker'),
    ('……','某人','insufficient'),
    (' @某人(O123) 的精彩视频','某人','insufficient'),
    ('#搞笑 #抽象','某人','other'),
    ('今天店里卖的服装很好看','服装店','other'),
])
def test_business_classification_is_only_discovery(caption,name,category):
    assert classify({'caption':caption,'nickname':name})[0]==category

def test_name_and_keyword_never_grant_publish_eligibility(store):
    add(store,'video12345','今天开门了','成人用品库存清仓本店',source={'query':'本店成人用品库存清仓'})
    item=data_view(store)['items'][0]
    assert item['category']=='merchant'
    assert not item['comment_preview']['content_match']
    assert item['comment_preview']['templates']==[]

def test_preview_uses_current_configuration_and_requires_detail(store):
    task=next(t for t in store.objects('task') if t['kind']=='adult_comments')
    text='我这边收尾货，店里如果有积压库存，可以先了解品类和数量。'
    store.put('task',dict(task,templates=[text]),task['id'])
    add(store,'video12345','本店成人用品库存清仓')
    result=data_view(store)
    row=result['items'][0]
    assert row['comment_preview']['content_match']
    assert row['comment_preview']['label']=='待详情核验'
    assert row['comment_preview']['templates']==[text]
    assert text in result['comment_templates'][0]['templates']

def test_contact_history_blocks_even_positive_content(store):
    add(store,'video12345','本店成人用品库存清仓')
    with store.connect() as db:
        db.execute('INSERT INTO history VALUES(?,?,?,?,?)',('ks','video12345','author1234','旧评论',time.time()))
    assert data_view(store)['items'][0]['comment_preview']['status']=='contacted'

def test_comment_records_do_not_merge_as_videos_or_become_targets(store):
    for ident in ('c1','c2'):
        add(store,'video12345','本店成人用品库存清仓',comment_id=ident,record_type='comments')
    result=data_view(store)
    assert result['summary']['unique']==2
    assert result['summary']['content_matches']==0
    assert all(r['category']=='comment' for r in result['items'])

def test_filters_and_empty_page_are_consistent(store):
    add(store,'video12345','本店成人用品库存清仓')
    add(store,'video99999','新闻报道其他店铺','新闻频道')
    result=data_view(store,category='inventory',q='本店',page=999)
    assert result['total']==1 and result['page']==1
    assert data_view(store,category='inventory',q='不存在')['total']==0

def test_reading_view_never_changes_execution_state(store):
    add(store,'video12345','本店成人用品库存清仓')
    before=store.rows('SELECT * FROM evidence')
    data_view(store)
    assert store.rows('SELECT * FROM evidence')==before
    assert not store.rows('SELECT * FROM attempts') and not store.rows('SELECT * FROM runs')


def test_preview_obeys_scope_and_generated_comment_for_exact_video(store):
    from jm_workbench.policies.comments import ADULT_CORE, candidates
    task=next(t for t in store.objects('task') if t['kind']=='adult_comments')
    add(store,'video12345','本店成人用品正常营业')
    assert not data_view(store)['items'][0]['comment_preview']['content_match']
    task=store.put('task',dict(task,adult_target='merchant',comment_mode='core_variants',comment_core=ADULT_CORE),task['id'])
    result=data_view(store)
    row=result['items'][0]
    assert row['category']=='merchant'
    assert row['comment_preview']['label']=='待详情核验'
    assert row['comment_preview']['templates']==candidates(task,row['data'])
    assert len(result['comment_templates'][0]['templates'])==3
    assert result['comment_templates'][0]['comment_core']==ADULT_CORE


def test_keyword_preview_accepts_related_news_without_changing_classification(store):
    task=next(t for t in store.objects('task') if t['kind']=='adult_comments')
    store.put('task',dict(task,adult_target='keyword',keywords=['成人用品店']),task['id'])
    add(store,'video12345','记者调查：成人用品店怎么经营','某新闻',source={'kind':'search','query':'成人用品店'})
    row=data_view(store)['items'][0]
    assert row['category']=='discussion'
    assert row['comment_preview']['content_match']
    assert row['comment_preview']['status']=='needs_detail'
    assert row['comment_preview']['templates']
    assert not store.rows('SELECT * FROM attempts')
