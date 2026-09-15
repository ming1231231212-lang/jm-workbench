import pytest
from jm_workbench.policies.rules import assess, validate_template, DEFAULTS, detail_ready

@pytest.mark.parametrize('text,ok', [
    ('本店成人用品库存积压，准备清仓', True), ('我们店情趣用品今天补货', True),
    ('库存处理 #成人用品', False), ('成人用品清仓', False), ('朋友的店成人用品库存清仓', False),
    ('本店成人用品无库存', False), ('本店成人用品库存已清完', False),
    ('新闻报道本店成人用品库存', False), ('本店成人用品招商加盟库存', False),
    ('我收成人用品尾货，本店库存', False), ('本店成人用品猫咪搞笑库存', False),
])
def test_inventory_evidence(text, ok):
    assert assess('adult_comments', text)[0] is ok

@pytest.mark.parametrize('text,ok', [
    ('本人22岁，想做陪玩，求职', True), ('我已成年，想做陪玩，求一份工作', True),
    ('我17岁想做陪玩求职', False), ('本人未满18岁，陪玩求职', False),
    ('陪玩招聘，18岁以上来', False), ('陪玩求职', False), ('成年一起打游戏', False),
    ('我20岁，高中还没毕业想做陪玩', False), ('我21岁，不找工作，陪玩求职记录', False),
])
def test_recruitment_evidence(text, ok):
    assert assess('peiwang_comments', text)[0] is ok

def test_templates_cannot_cross_business():
    for kind, cfg in DEFAULTS.items():
        validate_template(kind, cfg['templates'][0])
    with pytest.raises(ValueError):
        validate_template('adult_comments', DEFAULTS['peiwang_comments']['templates'][0])
    with pytest.raises(ValueError):
        validate_template('peiwang_comments', '招聘陪玩不限年龄，想做就来，保证每天轻松日入千元。')

def test_detail_required():
    assert not detail_ready('adult_comments', {'caption': '本店成人用品库存清仓'})[0]
