"""Keyword relevance on collected text, with exact search provenance."""
import re
from .rules import CATEGORY


def keyword_relevance(task, item):
    source = item.get('source') or {}
    if source.get('kind') == 'search':
        query = source.get('query')
    elif source.get('kind') == 'detail':
        origin = item.get('search_origin') or {}
        if origin.get('kind') != 'search' or origin.get('video_id') != item.get('video_id'):
            return False, '详情缺少与该视频绑定的关键词搜索来源'
        query = origin.get('query')
    else:
        return False, '缺少准确的关键词搜索来源'
    if not isinstance(query, str) or query not in task.get('keywords', []):
        return False, '来源关键词不在当前任务配置内'
    caption = str(item.get('caption') or item.get('title') or '')
    if any(w in caption for w in ('幼态', '儿童款', '未成年人形象', '儿童性玩具')):
        return False, '涉及未成年人性化商品的内容，不作为收货评论目标'
    text = re.sub(r'#[^\s#]+', '', caption).strip()
    if not any(w in text for w in CATEGORY):
        return False, '标题/正文没有成人用品主题证据，搜索命中或标签不代替内容判断'
    if re.search(r'(?:不是|并非|不属于|没有经营|不经营|不卖)(?:一家|这家)?(?:成人用品|情趣用品|夫妻用品|计生用品)', text):
        return False, '正文否定成人用品主题或经营内容'
    if any(w in text for w in ('晒猫', '猫咪', '女装', '鞋服', '服装', '旅游', '风景', '台球')):
        return False, '正文混有其他品类或无关主题，无法确认关键词内容一致'
    if not any(w in query for w in CATEGORY):
        if query not in text:
            return False, '正文未匹配本次搜索关键词'
    else:
        if '店' in query and not any(w in text for w in ('店', '门店', '商家', '营业', '外卖仓')):
            return False, '正文有成人用品主题，但缺少关键词要求的店铺内容'
        inventory = ('库存', '清仓', '清货', '尾货', '积压', '余货', '剩货', '停卖', '补货')
        if any(w in query for w in inventory) and not any(w in text for w in inventory):
            return False, '正文缺少本次关键词中的库存、补货或处置要素'
    return True, f'标题/正文与来源关键词“{query}”的成人用品主题及相关要素一致；不要求店主身份或库存'
