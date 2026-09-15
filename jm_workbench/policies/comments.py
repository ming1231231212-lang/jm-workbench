"""Bounded local paraphrases. A video's choice is stable, including on retries."""
import hashlib
import re
from .rules import validate_template

ADULT_CORE = '店里如果有积压或停卖的货可以找我哦'


def variants(core):
    if re.search(r'[\r\n\x00]', core):
        raise ValueError('核心文案请填写一行自然语言')
    validate_template('adult_comments', core)
    # Replace complete phrases only; never infer facts about the recipient.
    phrases = (
        ('店里', ('店里', '您店里', '店内')),
        ('如果有', ('如果有', '要是有', '若有')),
        ('积压或停卖的货', ('积压或停卖的货', '积压的货或停卖的货')),
        ('可以找我哦', ('可以找我哦', '可以找我聊聊哦', '可以和我说一声哦')),
    )
    texts = [core.rstrip('。！!')]
    for source, replacements in phrases:
        pattern = r'(?<!您)店里' if source == '店里' else re.escape(source)
        texts = list(dict.fromkeys(re.sub(pattern, lambda _: value, t, count=1)
                                   for t in texts for value in replacements))
    if len(texts) < 3:
        texts = [prefix + t for t in texts for prefix in ('', '您好，', '你好，')]
    result = []
    for text in texts:
        text += '。'
        try:
            validate_template('adult_comments', text)
        except ValueError:
            continue
        if text not in result:
            result.append(text)
    if len(result) < 2:
        raise ValueError('核心文案无法生成多种有效表达，请缩短后重试')
    return result


def candidates(task, item):
    if task.get('comment_mode', 'templates') != 'core_variants':
        return task.get('templates', [])
    pool = variants(task['comment_core'])
    key = '\0'.join((task['platform'], str(item.get('video_id', '')), task['comment_core']))
    index = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], 'big') % len(pool)
    # Do not try another paraphrase if this one is blocked by contact history.
    return [pool[index]]


def examples(task):
    if task.get('comment_mode', 'templates') != 'core_variants':
        return task.get('templates', [])
    pool = variants(task['comment_core'])
    return list(dict.fromkeys(pool[i] for i in (0, len(pool)//2, len(pool)-1)))


def target_description(task):
    if task['kind'] == 'peiwang_comments':
        return '正文明确成年且本人正在找陪玩工作；排除未成年人和招聘方。'
    if task.get('adult_target') == 'keyword':
        return '标题/正文与本次搜索关键词主题及相关要素一致即可；无需店主身份或库存，可包含相关报道和讨论。当前未核验画面或口播。'
    if task.get('adult_target', 'inventory') == 'merchant':
        return '正文明确是自己经营的成人用品门店、厂家或仓库；无需提前说明库存。'
    return '正文明确成人用品、自家经营，并有库存、补货或清仓等货品线索。'
