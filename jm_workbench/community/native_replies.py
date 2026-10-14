"""Native top-level replies for Tieba and Juejin; no guessed coordinates or retries."""
from .native import NativeStopped, NativeUnknown, normalized, profile_key
from .native_articles import inside, visible, find, copy, paste, author_scope
from .registry import thread_url


def reply_editor(s, platform):
    roots=[n for n in s['nodes'] if n.get('id')==('tb-editor-pb-content' if platform=='tieba' else 'comment-box')]
    if len(roots)!=1:raise NativeStopped('评论区域不唯一，未提交')
    candidates=[n for n in visible(s,roots[0]['key']) if n.get('text_input') and n.get('focusable')]
    if len(candidates)!=1:raise NativeStopped('评论输入框未就绪，未提交')
    return candidates[0]


def prepare_reply(p,account,binding,payload,target):
    platform=account['platform'];target=thread_url(platform,target);body=payload.get('body','')
    if platform not in ('tieba','juejin') or not 20<=len(body)<=2000:raise NativeStopped('本机评论内容或平台无效')
    p.ui.call('open',url=target);s=p._wait_page(target)
    title=normalized(payload.get('source_title',''))
    anchors=[normalized(x) for x in payload.get('source_excerpt','').splitlines() if len(normalized(x))>=20 and normalized(x)!=title]
    if not title or title not in normalized(s['text']) or not anchors or not any(x in normalized(s['text']) for x in anchors):
        raise NativeStopped('原帖具体内容与评论依据不符，未提交')
    if any(normalized(n.get('name'))==normalized(body) for n in s['nodes'] if n['type']=='Text'):
        raise NativeStopped('原帖已经出现相同评论，禁止再次提交')
    if platform=='tieba':
        mine=[n for n in visible(s) if n['type']=='Hyperlink' and n.get('name')=='我的' and profile_key(n.get('value',''))==profile_key(binding['profile_url'])]
        if len(mine)!=1:raise NativeStopped('贴吧原帖的当前账号不一致，未提交')
        placeholders=[n for n in s['nodes'] if n['type']=='Text' and n.get('name','').startswith('参与讨论涨经验')]
        if len(placeholders)!=1:raise NativeStopped('贴吧顶层评论入口不唯一，未提交')
        if not placeholders[0]['visible']:
            p.ui.call('find',text=placeholders[0]['name'],expected_url=target);s=p._snapshot(target)
            placeholders=[n for n in visible(s) if n['type']=='Text' and n.get('name','').startswith('参与讨论涨经验')]
        if len(placeholders)!=1:raise NativeStopped('贴吧评论入口不可见，未提交')
        p._click(placeholders[0],target)
    else:
        p.ui.call('keys',text='^{HOME}',expected_url=target);s=p._snapshot(target)
        avatar=find(s,binding['name']+'的头像')
        p._click(avatar,target);s=p._snapshot(target)
        own=[n for n in visible(s) if n['type']=='Hyperlink' and n.get('name')==binding['name'] and profile_key(n.get('value',''))==profile_key(binding['profile_url'])]
        if len(own)!=1:raise NativeStopped('掘金当前登录账号不一致，未提交')
        p._click(find(s,binding['name']+'的头像'),target)
        p.ui.call('open',url=target+'#comment-box')
    s=p._snapshot(target);node=reply_editor(s,platform)
    if normalized(copy(p,node,target)):raise NativeStopped('评论框有未提交内容，已保留原稿')
    paste(p,node,target,body);s=p._snapshot(target);node=reply_editor(s,platform)
    if normalized(copy(p,node,target))!=normalized(body):raise NativeStopped('评论全文无法核对，未提交')
    s=p._snapshot(target);submit=find(s,'发布' if platform=='tieba' else '发送',types=('Button','Text'))
    return {'url':target,'submit':submit,'platform':platform}


def verify_reply(p,account,binding,payload,ready):
    for _ in range(p.poll_attempts):
        p.sleep(1)
        try:
            s=p._snapshot(ready['url']);node=reply_editor(s,account['platform'])
            if normalized(copy(p,node,ready['url'])):continue
            author=author_scope(s,binding,payload['body'])
            if not author:continue
            p.sleep(2);later=p._snapshot(ready['url'])
            if not author_scope(later,binding,payload['body']):continue
            return {'url':ready['url'],'post_id':ready['url'].rsplit('/',1)[-1],
                    'visibility':'account_visible','body':payload['body'],'author_url':author,'author_name':binding['name']}
        except Exception:pass
    raise NativeUnknown('单次提交后未核实新增评论和作者，禁止自动重发')
