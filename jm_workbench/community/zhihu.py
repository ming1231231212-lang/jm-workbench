"""Zhihu web handoff contracts. No private API, browser connection, or submit call."""
import re
from urllib.parse import urlparse


def _content(value):
    value = value.strip()
    try:
        p = urlparse(value)
        valid = (len(value) <= 2000 and not re.search(r'[\x00-\x20\\]', value)
                 and p.scheme == 'https' and not p.username and not p.password
                 and p.port in (None, 443))
    except ValueError:
        valid = False
    if valid:
        article = re.fullmatch(r'/p/([1-9][0-9]{3,23})/?', p.path)
        answer = re.fullmatch(r'/question/([1-9][0-9]{3,23})/answer/([1-9][0-9]{3,23})/?', p.path)
        if p.hostname == 'zhuanlan.zhihu.com' and article:
            return 'article', article.group(1), 'https://zhuanlan.zhihu.com/p/' + article.group(1)
        if p.hostname == 'www.zhihu.com' and answer:
            return 'answer', answer.group(2), 'https://www.zhihu.com' + p.path.rstrip('/')
    raise ValueError('请填写知乎文章或具体回答的HTTPS链接；文章用 zhuanlan.zhihu.com/p/编号，回答用 www.zhihu.com/question/编号/answer/编号')


def comment_target_url(value):
    return _content(value)[2]


def comment_target_key(value):
    kind, ident, _ = _content(value)
    # A different question segment must not bypass the same answer's reservation.
    return kind + ':' + ident


def article_url(value):
    kind, _, canonical = _content(value)
    if kind != 'article':
        raise ValueError('知乎专栏文章请登记发布后的文章链接，不是回答链接')
    return canonical


def validate_payload(payload):
    if payload.get('kind') == 'reply' and len(payload['body']) > 2000:
        raise ValueError('工作台知乎评论正文最多2000字，请围绕原帖提供具体内容')


def record_url(payload, target, value):
    if payload.get('kind') != 'reply':
        return article_url(value)
    actual = comment_target_url(value)
    if actual != comment_target_url(target):
        raise ValueError('知乎评论结果链接必须对应原帖，不能登记其他文章或回答')
    return actual
