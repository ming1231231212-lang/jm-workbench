"""Read-only business interpretation; discovery labels never grant send permission."""
import json
import re
import time
from collections import Counter
from ..policies.rules import assess, detail_ready
from .guard import comment_due, contact_reason

CATEGORIES = {
    'inventory': '成人货源线索',
    'merchant': '门店 / 品牌线索',
    'jobseeker': '成年陪玩求职',
    'discussion': '新闻 / 招商 / 行业讨论',
    'other': '其他内容',
    'insufficient': '信息不足',
    'comment': '采集到的评论',
}


def classify(item):
    caption = str(item.get('caption') or item.get('title') or item.get('desc') or '')
    nickname = str(item.get('nickname') or item.get('user_name') or item.get('author_name') or '')
    if item.get('record_type') == 'comments' or item.get('comment_id'):
        return 'comment', '这是采集到的用户评论，不是视频正文，不进入视频评论目标判断'
    if assess('adult_comments', caption)[0]:
        return 'inventory', '正文符合成人品类、自有经营和实物线索；仍需详情核验，并非已确认有尾货'
    if assess('peiwang_comments', caption)[0]:
        return 'jobseeker', '正文有成年和本人陪玩求职意向；仍需详情核验'
    discussion = ('新闻', '记者', '报道', '加盟', '招商', '教程', '商业思维', '创业项目', '干货分享', '科普', '骗局',
                  '诈骗', '投诉', '被偷', '盗窃', '夜闯', '销售鬼才', '刑事辩护', '行业好做', '行业到底', '副业陷阱')
    media_hint = re.search(r'新闻|频道|广播|热线|财经|杂谈|韬略|中安在线|荆楚网', nickname)
    # A media-name hint can exclude a record, but a shop-name hint cannot approve one.
    if any(w in caption for w in discussion) or (media_hint and len(caption.strip()) > 5):
        return 'discussion', '内容偏新闻、招商或行业讨论，发视频的人不等于报道中的持货店主'
    merchant = re.search(r'本店|我们店|我的店|开店日常|老板娘日常|守店|实体店|诚信经营|无套路经营|口碑店|批发|厂家|库存|清仓', caption)
    name_hint = re.search(r'旗舰店|成人|情趣|用品|小商品城', nickname)
    if merchant or name_hint:
        return 'merchant', '仅有门店、经营或昵称线索；尚不能证明成人用品品类、自有库存和尾货处置意愿'
    body = re.sub(r'#[^\s#]+', '', caption).strip()
    placeholder = not re.search(r'[\u4e00-\u9fffA-Za-z0-9]', body) or bool(re.fullmatch(r'@.*的精彩视频', body))
    if placeholder:
        # Specific non-business tags explain an exclusion even without body text.
        if any(w in caption for w in ('搞笑', '抽象', 'AI灵境', '台球', '服装')):
            return 'other', '已有内容属于其他话题，没有对应收货或招募线索'
        return 'insufficient', '只有话题、占位文字或简介过短，不能据此判断实际视频内容'
    return 'other', '已有正文没有符合成人货源或成年陪玩求职的证据'


def record_key(row):
    item = row['data']
    if item.get('record_type') == 'comments' or item.get('comment_id'):
        return (row['platform'], 'comment', str(item.get('comment_id') or row['id']))
    return (row['platform'], 'video', str(row.get('video_id') or item.get('video_id') or item.get('note_id') or row['id']))


def combine(rows):
    groups = {}
    for row in rows:  # newest evidence first; never reuse older detail as if freshly verified
        key = record_key(row)
        if key not in groups:
            groups[key] = {**row, 'occurrences': 0, 'keywords': [], 'source_batches': []}
        item = groups[key]
        item['occurrences'] += 1
        source = row['data'].get('source') or {}
        query = source.get('query') or row['data'].get('source_keyword')
        if query and query not in item['keywords']:
            item['keywords'].append(query)
        if row['run_id'] not in item['source_batches']:
            item['source_batches'].append(row['run_id'])
    return list(groups.values())


def preview(store, row, tasks, now):
    item = row['data']
    caption = str(item.get('caption') or item.get('title') or item.get('desc') or '')
    evaluations = {kind: assess(kind, caption) for kind in ('adult_comments', 'peiwang_comments')}
    kind = next((k for k, (ok, _) in evaluations.items() if ok), None)
    if item.get('record_type') == 'comments' or item.get('comment_id'):
        kind = None
    base = {'content_match': bool(kind), 'templates': [], 'task_names': [], 'business': kind or '', 'label': '不会评论', 'status': 'not_matched'}
    if not kind:
        return dict(base, reason='正文未通过任一评论业务规则；门店昵称、搜索词和业务分类不能代替正文证据')
    applicable = [t for t in tasks if t['kind'] == kind and t['platform'] == row['platform'] and t['enabled']]
    base['task_names'] = [t['name'] for t in applicable]
    base['templates'] = list(dict.fromkeys(text for t in applicable for text in t['templates']))
    if not applicable:
        return dict(base, status='unconfigured', label='未配置对应任务', reason='内容初筛通过，但没有启用的同平台评论任务')
    with store.connect() as db:
        for table in ('attempts', 'history'):
            if db.execute(f'SELECT 1 FROM {table} WHERE platform=? AND video_id=?', (row['platform'], row['video_id'])).fetchone():
                return dict(base, status='contacted', label='已有接触记录', reason='此视频已尝试联系，系统不会再次发送')
    ready, reason = detail_ready(kind, item)
    if not ready or not 0 <= now - (item.get('observed_at') or 0) <= 120:
        return dict(base, status='needs_detail', label='待详情核验', reason='正文初筛通过；须重新读取准确视频详情，核验作者、评论权限和时效')
    if store.rows('SELECT 1 FROM risk WHERE platform=?', (row['platform'],)):
        return dict(base, status='risk', label='平台已暂停', reason='平台限制未解除，不能发送')
    with store.connect() as db:
        available = [text for text in base['templates'] if not contact_reason(db, row['platform'], item, text, now)]
    if not available:
        return dict(base, status='contacted', label='近期已联系或用过文案', reason='作者或相同文案近期有接触记录，不重复打扰')
    due = min(comment_due(store, row['platform'], t, now) for t in applicable)
    if due > now:
        return dict(base, status='waiting', label='等待允许发送的时间', reason='内容条件符合，仍受任务排队、发送时段和共享限额约束')
    return dict(base, status='recheck', label='执行时再次核验', reason='内容条件符合；本页仅为预览，发送前仍需核验固定账号、任务和共享预算')


def data_view(store, q='', decision='', page=1, batch='all', category='', now=None):
    now = time.time() if now is None else now
    batches = store.rows('SELECT run_id,COUNT(*) records,MAX(created) latest FROM evidence GROUP BY run_id ORDER BY latest DESC')
    latest = next((b['run_id'] for b in batches if b['run_id'] != 'legacy'), 'all')
    selected = latest if batch == 'latest' else batch
    args = () if selected == 'all' else (selected,)
    rows = store.rows('SELECT * FROM evidence '+('' if selected == 'all' else 'WHERE run_id=? ')+'ORDER BY id DESC', args)
    for row in rows:
        row['data'] = json.loads(row['data'])
    items = combine(rows)
    tasks = store.objects('task')
    for row in items:
        key, reason = classify(row['data'])
        row.update(category=key, category_label=CATEGORIES[key], classification_reason=reason)
        row['comment_preview'] = preview(store, row, tasks, now)
        # Link only the exact known video on an implemented site.
        row['video_url'] = 'https://www.kuaishou.com/short-video/'+row['video_id'] if row['platform'] == 'ks' and re.fullmatch(r'[A-Za-z0-9_-]{8,64}', row['video_id'] or '') else ''
    counts = Counter(r['category'] for r in items)
    summary = {'records': len(rows), 'unique': len(items), 'duplicates': len(rows)-len(items),
               'content_matches': sum(r['comment_preview']['content_match'] for r in items),
               'categories': [{'id': k, 'label': label, 'count': counts[k]} for k, label in CATEGORIES.items()]}
    filtered = [r for r in items if (not category or r['category'] == category) and (not decision or r['decision'] == decision)
                and (not q or q.casefold() in json.dumps(r, ensure_ascii=False).casefold())]
    total = len(filtered)
    page = min(max(1, page), max(1, (total+29)//30))
    run_names = {r['id']: json.loads(r['snapshot'])['task']['name'] for r in store.rows('SELECT id,snapshot FROM runs')}
    for entry in batches:
        entry['name'] = '历史迁入' if entry['run_id'] == 'legacy' else run_names.get(entry['run_id'], '只读采集批次')
    templates = [{'task_id': t['id'], 'name': t['name'], 'platform': t['platform'], 'kind': t['kind'],
                  'enabled': t['enabled'], 'templates': t['templates'], 'start_hour': t['start_hour'],
                  'end_hour': t['end_hour']} for t in tasks if t['kind'] != 'crawler']
    return {'items': filtered[(page-1)*30:page*30], 'total': total, 'page': page, 'summary': summary,
            'batches': batches, 'selected_batch': selected, 'requested_batch': batch,
            'comment_templates': templates, 'categories': CATEGORIES}
