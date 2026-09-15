"""Text-only business evidence. Search words and account nicknames are never proof."""
import re

ID_RE = re.compile(r'^[a-zA-Z0-9_-]{8,64}$')
CATEGORY = ('成人用品', '情趣用品', '夫妻用品', '性用品', '计生用品', '避孕套', '情趣润滑液')
DEFAULTS = {
    'adult_comments': {'name': '成人用品尾货收购', 'keywords': ['成人用品库存处理', '情趣用品清仓', '成人用品店补货'],
        'templates': ['我这边做尾货回收，店里如果有积压或停卖的货，想了解一下品类和数量。']},
    'peiwang_comments': {'name': '陪玩18+招募', 'keywords': ['成年陪玩求职', '18岁以上陪玩找工作'],
        'templates': ['看到你在找陪玩工作，我们招募18岁以上的陪玩，可以先交流游戏经验和可接单时间。']},
}


def validate_template(kind, text):
    if not 15 <= len(text) <= 100:
        raise ValueError('评论长度需要15至100字')
    if re.search(r'https?://|www\.|微信|加微|私信|扫码|手机号|联系电话|[0-9]{7,}|包赚|保底收入|日入|躺赚|同城|关注很久|保证高价', text, re.I):
        raise ValueError('模板含外联、收入承诺或未经核实的陈述')
    if kind == 'adult_comments':
        if any(w in text for w in ('陪玩', 'p玩', '招聘', '招募', '兼职', '收设备', '接店')):
            raise ValueError('成人尾货模板不能混入陪玩或其他业务')
        if not any(w in text for w in ('尾货', '库存', '积压', '余货')):
            raise ValueError('模板缺少收货语境')
        if not any(w in text for w in ('如果', '是否有', '有没有', '若有', '要是有')):
            raise ValueError('统一模板须使用条件式询问，避免假定商家正在清仓')
    elif kind == 'peiwang_comments':
        if not re.search(r'18\+|18岁以上|年满18', text) or '陪玩' not in text or not any(w in text for w in ('招募', '招聘')):
            raise ValueError('陪玩模板须明确18岁以上招募')
        if any(w in text for w in CATEGORY + ('尾货', '未成年', '学生也可', '不限年龄')):
            raise ValueError('陪玩模板包含跨业务或年龄冲突')
    return text


def assess(kind, caption, adult_target='inventory'):
    text = re.sub(r'#[^\s#]+', '', caption or '').strip()
    common = ('新闻', '报道', '记者', '听说', '据说', '有人说', '骗局', '避坑', '教程', '假如', '如果', '帮朋友')
    if any(w in text for w in common) or any(w in text for w in ('“', '”', '「', '」', '"')):
        return False, '存在转述、假设或冲突内容'
    if kind == 'adult_comments':
        if adult_target not in ('inventory', 'merchant'):
            return False, '未注册的成人用品评论范围'
        if not any(w in text for w in CATEGORY):
            return False, '正文缺少成人用品品类证据'
        conflicts = ('晒猫', '猫咪', '旅游', '风景', '女装', '鞋服', '搞笑', '测评', '体验', '买家', '招商', '加盟', '代运营', '代理', '设备销售', '售货机出售', '朋友的店', '别人家', '探店', '路过', '怎么开', '如何开', '想开', '打算开', '收尾货', '收购', '回收', '不清仓', '不清货', '没有库存', '暂无', '无库存', '已售罄', '卖完了', '已清完', '不是本店', '不卖', '不做', '不再经营', '没有成人', '无货', '没货', '没开', '计划', '已处理完')
        if any(w in text for w in conflicts) or re.search(r'(我|我们|长期|大量|专业)收.{0,12}(尾货|库存|成人用品|情趣用品)', text):
            return False, '消费、同行收货、招商或否定内容，自动跳过'
        if any(w in text for w in ('培训', '课程', '行业分析', '创业建议', '创业项目', '商业思维', '分享经验', '服装', '不是我的店', '不是我们店', '不是我店', '被偷', '盗窃', '夜闯', '被盗', '曝光', '投诉', '刑事辩护')):
            return False, '行业教学、其他品类或经营身份冲突，自动跳过'
        own = re.search(r'本店|我店|我们店|我的店|自家店|我们厂|本厂|自家工厂|本仓|我们仓库|自家仓库', text)
        opened = adult_target == 'merchant' and re.search(r'(?:我|我们)(?:开了|经营着|经营|开的)(?:一家|这家)?(?:成人用品|情趣用品|夫妻用品|计生用品)店', text)
        if not own and not opened:
            return False, '正文没有作者自己经营的证据'
        if adult_target == 'inventory' and not any(w in text for w in ('补货', '库存', '货架', '现货', '清仓', '清货', '尾货', '积压', '余货', '剩货')):
            return False, '缺少实际库存或补货线索'
        return True, ('正文明确成人用品及自家经营，无需先说明库存' if adult_target == 'merchant' else '正文明确品类、自家经营和货品')
    if kind == 'peiwang_comments':
        if any(w in text for w in CATEGORY + ('未成年', '未满18', '没满18', '不满18', '高中', '初中', '中学', '小学生', '招聘', '招募', '招人', '招陪玩', '公会收人', '不找工作', '不求职')) or re.search(r'(?<!\d)(?:[0-9]|1[0-7])岁', text):
            return False, '年龄、业务或招聘方身份冲突'
        adult = re.search(r'已成年|我成年|本人已?成年|年满18|18\+|(?<!\d)(?:1[89]|[2-5]\d)岁', text)
        seek = re.search(r'我想找|我找|本人求职|本人找|求职|求一份|想做陪玩|找陪玩工作|找个陪玩工作', text)
        if not adult or not seek or not re.search(r'陪玩|p玩', text, re.I):
            return False, '需正文同时说明成年和本人陪玩求职意向'
        return True, '正文明确成年和本人陪玩求职意向'
    return False, '未注册的评论业务'


def assess_item(task, item):
    if item.get('record_type') == 'comments' or item.get('comment_id'):
        return False, '采集到的评论不能作为视频评论目标'
    if task['kind'] == 'adult_comments' and task.get('adult_target') == 'keyword':
        from .relevance import keyword_relevance
        return keyword_relevance(task, item)
    nickname = str(item.get('nickname') or item.get('author_name') or '')
    if task['kind'] == 'adult_comments' and re.search(r'新闻|频道|广播|热线|财经|杂谈|中安在线|荆楚网', nickname):
        return False, '媒体或行业账号，不能认定为经营者自己的视频'
    return assess(task['kind'], item.get('caption', ''), task.get('adult_target', 'inventory'))


def detail_ready(kind, item, adult_target='inventory', keywords=None):
    if not ID_RE.fullmatch(str(item.get('video_id', ''))) or not ID_RE.fullmatch(str(item.get('author_id', ''))):
        return False, '目标视频或作者标识不完整'
    if item.get('detail_verified') is not True or item.get('source', {}).get('kind') != 'detail':
        return False, '缺少准确绑定的视频详情'
    if item.get('can_comment') is not True:
        return False, '视频没有明确开放评论'
    return assess_item({'kind': kind, 'adult_target': adult_target, 'keywords': keywords or []}, item)
