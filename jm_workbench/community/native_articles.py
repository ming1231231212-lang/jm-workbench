"""Native plain-text article preparation; final submit belongs to the caller."""
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit,parse_qs

from .native import NativeStopped, NativeUnknown, normalized, profile_key
from .registry import compose_url, thread_url


def inside(s, key, root):
    by = {n['key']: n for n in s.get('nodes', [])}
    seen = set()
    while key and key not in seen:
        if key == root: return True
        seen.add(key); key = by.get(key, {}).get('parent')
    return False


def rendered(value):
    value = re.sub(r'(?m)^\s*(?:#{1,6}\s+|[-*+]\s+)', '', value)
    value = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', value)
    return normalized(value.replace('**', '').replace('`', ''))


def common_parent(s, keys):
    by = {n['key']: n for n in s['nodes']}
    key = keys[0]
    for _ in range(45):
        if all(inside(s, k, key) for k in keys): return key
        key = by.get(key, {}).get('parent')
        if not key: break
    raise NativeStopped('编辑器区域无法唯一核对，未提交')


def visible(s, root=None):
    return [n for n in s['nodes'] if n.get('visible') and (not root or inside(s, n['key'], root))]


def find(s, name, root=None, types=()):
    matches = [n for n in visible(s, root) if normalized(n.get('name')) == normalized(name)
               and (not types or n['type'] in types)]
    for type in ('Button', 'ListItem', 'RadioButton', 'Edit', 'Text', 'Group','Image'):
        preferred = [n for n in matches if n['type'] == type]
        if preferred:
            if len(preferred) != 1: break
            return preferred[0]
    raise NativeStopped('找不到唯一的原生控件：' + name)


def fields(s, platform):
    if platform == 'zhihu':
        edits = [n for n in s['nodes'] if n['type'] == 'Edit' and not n.get('name')]
        if len(edits) == 2: return edits[0], edits[1]
    elif platform == 'juejin':
        titles = [n for n in visible(s) if n['type'] == 'Edit' and n.get('name') == '输入文章标题...']
        docs = {n['key'] for n in s['nodes'] if n['type'] == 'Document'}
        candidates = [n for n in s['nodes'] if n['type'] == 'Edit' and not n.get('name') and n.get('focusable')]
        direct = [n for n in candidates if n.get('parent') in docs]
        bodies = direct if len(direct) == 1 else [n for n in candidates if not n.get('visible')]
        if len(titles) == len(bodies) == 1: return titles[0], bodies[0]
    else:
        result = []
        for ident in ('tb-editor-title', 'tb-editor-content'):
            roots = [n for n in s['nodes'] if n.get('id') == ident]
            if len(roots) != 1: break
            edits = [n for n in s['nodes'] if inside(s,n['key'],roots[0]['key']) and n.get('text_input') and n.get('focusable')]
            if len(edits) != 1: break
            result.append(edits[0])
        if len(result) == 2: return tuple(result)
    raise NativeStopped('文章输入框发生变化，未覆盖原稿')


def link_destination(value):
    u=urlsplit(value)
    if u.scheme=='https' and u.hostname=='tieba.baidu.com' and u.path=='/mo/q/checkurl':
        urls=parse_qs(u.query).get('url',[])
        if len(urls)==1 and urlsplit(urls[0]).scheme in ('http','https'):return urls[0]
    if u.scheme=='https' and u.hostname=='link.zhihu.com' and u.path in ('','/'):
        urls=parse_qs(u.query).get('target',[])
        if len(urls)==1 and urlsplit(urls[0]).scheme in ('http','https'):return urls[0]
    return value


def semantic_value(s, root, copied, html='',strict=True):
    """Resolve rich-editor link labels using only that editor's actual hrefs."""
    if not normalized(copied):
        return ''
    if html:
        class Fragment(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True); self.parts=[]; self.link=0; self.custom=False; self.resolved=False
            def handle_starttag(self, tag, attrs):
                attrs=dict(attrs)
                if tag == 'a':
                    if self.link:raise NativeStopped('复制的正文链接结构无效，未提交')
                    href=attrs.get('href','');self.custom='blot-link' in attrs.get('class','').split();self.resolved=False
                    if re.match(r'https?://',href):self.parts.append(href);self.resolved=True
                    elif not self.custom:raise NativeStopped('复制的正文链接地址无效，未提交')
                    self.link=1
                elif tag=='span' and self.link and self.custom and 'editor-blot-link' in attrs.get('class','').split():
                    href=attrs.get('data-url','')
                    if self.resolved or not re.match(r'https?://',href):raise NativeStopped('贴吧链接地址不唯一或无效，未提交')
                    self.parts.append(href);self.resolved=True
            def handle_endtag(self, tag):
                if tag=='a':
                    if not self.resolved:raise NativeStopped('复制的正文链接缺少实际地址，未提交')
                    self.link=0
            def handle_data(self, value):
                if not self.link:self.parts.append(value)
        match=re.search(r'<!--StartFragment-->(.*?)<!--EndFragment-->',html,re.S)
        if match:
            parser=Fragment();parser.feed(match[1]);return ''.join(parser.parts)
    by = {n['key']: n for n in s.get('nodes', [])}
    parts = []
    for n in s.get('nodes', []):
        if n['key'] == root or not inside(s, n['key'], root):
            continue
        parent = n.get('parent'); seen = set(); nested_link = False
        while parent and parent != root and parent not in seen:
            seen.add(parent)
            if by.get(parent, {}).get('type') == 'Hyperlink':
                nested_link = True; break
            parent = by.get(parent, {}).get('parent')
        if nested_link:
            continue
        if n['type'] == 'Hyperlink':
            href = link_destination(n.get('value', ''))
            if not re.match(r'https?://', href):
                if strict:raise NativeStopped('正文链接的实际地址无法核对，未提交')
                parts.append(n.get('name',''));continue
            parts.append(href)
        elif n['type'] == 'Text':
            parts.append(n.get('name', ''))
    return ''.join(parts) if parts else copied


def copy(p, node, url):
    p._snapshot(url)
    copied = p.ui.call('focus-copy', key=node['key'], expected_url=url)
    return semantic_value(p._snapshot(url), node['key'], copied['value'],copied.get('html',''))


def paste(p, node, url, text):
    p._snapshot(url)
    copied = p.ui.call('focus-paste', key=node['key'], expected_url=url, text=text)
    value = semantic_value(p.ui.call('follow_editor'), node['key'], copied['value'],copied.get('html',''))
    # Clipboard reads may precede the browser's rich-link conversion. Re-read
    # the same editor only; never paste the body again or accept a partial match.
    for _ in range(3):
        if normalized(value)==normalized(text):break
        p.sleep(.5);value=copy(p,node,url)
    if normalized(value) != normalized(text): raise NativeStopped('原生文章全文回读不一致，未提交')


def editor(p):
    for _ in range(p.poll_attempts):
        try:
            s = p.ui.call('follow_editor')
            if s.get('text'): return s
        except NativeStopped:
            pass
        p.sleep(.5)
    raise NativeStopped('原生文章编辑器未就绪，未提交')


def selected_tag(s, tag, box):
    scope=box['parent']
    return any(n['type']=='Text' and normalized(n.get('name'))==normalized(tag) and n.get('parent')!=scope
               for n in visible(s,scope))


def _tag(p, s, url, tag, platform, root=None):
    if platform == 'zhihu':
        p._click(find(s, '添加话题', root), url)
        s = p._snapshot(url); box = find(s, '搜索话题', root, ('Edit',))
    else:
        boxes = [n for n in visible(s, root) if n['type'] == 'Edit' and re.search('标签|搜索', n.get('name', ''))]
        cached=getattr(p,'_native_tag_box',None)
        if not boxes and cached and cached[0]==url:
            boxes=[n for n in visible(s,root) if n['type']=='Edit' and n['key']==cached[1]]
        if not boxes:
            hints=[n for n in visible(s,root) if normalized(n.get('name'))=='请搜索添加标签']
            if hints:
                label=find(s, '请搜索添加标签', root);scope=label['parent']
                p._click(label, url);s = p._snapshot(url)
            else:
                labels=[n for n in visible(s,root) if normalized(n.get('name'))=='添加标签：']
                if len(labels)!=1:raise NativeStopped('标签输入区域无法核对，未提交')
                index=s['nodes'].index(labels[0]);groups=[n for n in s['nodes'][index+1:] if n['type']=='Group' and n.get('parent')==labels[0]['parent']]
                if not groups:raise NativeStopped('标签输入区域已变化，未提交')
                scope=groups[0]['key']
            boxes = [n for n in visible(s, scope) if n['type'] == 'Edit' and not n.get('name') and n.get('rect', [0,0,0,100])[3] <= 70]
        if len(boxes) != 1: raise NativeStopped('标签搜索框不唯一，未提交')
        box = boxes[0]
        p._native_tag_box=(url,box['key'])
        if selected_tag(s,tag,box):return s
    p.ui.call('paste', key=box['key'], expected_url=url, text=tag)
    for _ in range(p.poll_attempts):
        p.sleep(.4); s = p._snapshot(url)
        try:
            exact=[n for n in visible(s,root) if n['type'] in ('ListItem','Button') and n.get('name')==tag]
            option = exact[0] if len(exact)==1 else find(s, tag, root, ('ListItem','Button'))
            p._click(option, url)
            return p._snapshot(url)
        except NativeStopped:
            pass
    raise NativeStopped('实际标签选项未核对，未提交：' + tag)


def _zhihu(p, s, url, payload):
    if not any(n.get('name')=='文章话题' for n in visible(s)):
        p._click(find(s, '发布设置', types=('Button',)), url);s = p._snapshot(url)
    if any(normalized(n.get('name')) == '无声明' for n in visible(s)):
        p._click(find(s, '无声明'), url); s = p._snapshot(url)
        options = [n for n in visible(s) if n['type'] in ('ListItem','RadioButton') and '包含AI辅助创作' in normalized(n.get('name'))]
        if len(options) != 1: raise NativeStopped('知乎AI辅助创作声明未核对，未提交')
        p._click(options[0], url); s = p._snapshot(url)
    if not any('包含AI辅助创作' in normalized(n.get('name')) for n in visible(s)):
        raise NativeStopped('知乎AI创作声明未选定，未提交')
    labels=[n for n in visible(s) if n.get('name')=='文章话题']
    scope=labels[0]['parent'] if len(labels)==1 else None
    for tag in payload.get('platform_tags', []):
        if not any(normalized(n.get('name'))==normalized(tag) and n['type']=='Text' for n in visible(s,scope)):
            s = _tag(p, s, url, tag, 'zhihu')
    for tag in payload.get('platform_tags', []):
        if not any(normalized(n.get('name')) == normalized(tag) and n['type'] == 'Text' for n in visible(s,scope)):
            raise NativeStopped('知乎文章话题未正确保留，未提交')
    return find(s, '发布', types=('Button',))


def _juejin(p, s, url, payload, target):
    if not any(n['type']=='Button' and n.get('name')=='确定并发布' for n in visible(s)):
        p._click(find(s, '发布', types=('Button',)), url);s = p._snapshot(url)
    confirm = find(s, '确定并发布', types=('Button',))
    labels = [n for n in visible(s) if n.get('name') in ('分类','文章分类')]
    root = common_parent(s, [confirm['key'], labels[0]['key']]) if labels else None
    labels=[n for n in visible(s,root) if normalized(n.get('name')) in ('分类','分类：','文章分类')]
    if len(labels)!=1:raise NativeStopped('掘金分类区域无法核对，未提交')
    begin=s['nodes'].index(labels[0])+1
    end=next((i for i,n in enumerate(s['nodes'][begin:],begin) if normalized(n.get('name')) in ('添加标签：','请搜索添加标签')),len(s['nodes']))
    choices=[n for n in s['nodes'][begin:end] if n.get('visible') and n['type']=='Text' and normalized(n.get('name'))==normalized(target)]
    if len(choices)!=1:raise NativeStopped('掘金所选分类不唯一，未提交')
    category = choices[0]
    p._click(category, url); s = p._snapshot(url)
    category = next(n for n in s['nodes'] if n['key']==category['key'])
    if p.ui.call('selected', key=category['key'], expected_url=url).get('selected') is not True:
        raise NativeStopped('掘金文章分类未选定，未提交')
    for tag in payload.get('platform_tags', []): s = _tag(p, s, url, tag, 'juejin', root)
    summaries = [n for n in visible(s, root) if n['type'] == 'Edit' and '摘要' in n.get('name', '')]
    if not summaries:
        summaries = [n for n in visible(s, root) if n['type'] == 'Edit' and not n.get('name') and n.get('rect', [0,0,0,0])[3] > 70]
    if len(summaries) != 1: raise NativeStopped('文章摘要输入框未核对，未提交')
    summary = re.sub(r'[#\n]+', ' ', payload['body'])[:100]
    p.ui.call('paste', key=summaries[0]['key'], expected_url=url, text=summary)
    s = p._snapshot(url)
    box=next((n for n in s['nodes'] if n['key']==getattr(p,'_native_tag_box',('',None))[1]),None)
    for tag in payload.get('platform_tags', []):
        if not box or not selected_tag(s,tag,box):
            raise NativeStopped('掘金实际标签未正确保留，未提交')
    return find(s, '确定并发布', root, ('Button',))


def _tieba(p, s, url, payload, target):
    title, body = fields(s, 'tieba'); root = common_parent(s, [title['key'], body['key']])
    for name in ('发布到吧',target):
        if len([n for n in s['nodes'] if normalized(n.get('name'))==normalized(name) and inside(s,n['key'],root)])!=1:
            raise NativeStopped('贴吧发布板块无法唯一核对，未提交')
    labels=[n for n in s['nodes'] if n.get('name')=='贴子含AI内容' and inside(s,n['key'],root)]
    if len(labels)==1 and not labels[0].get('visible'):
        p.ui.call('find',text='贴子含AI内容',expected_url=url);s=p._snapshot(url)
    label = find(s, '贴子含AI内容', root)
    row = next((n for n in s['nodes'] if n['key'] == label.get('parent')), None)
    if not row: raise NativeStopped('贴吧AI内容声明无法核对，未提交')
    state = p.ui.call('checkbox', key=row['key'], expected_url=url)
    if state.get('checked') is False:
        p._click(label, url); s = p._snapshot(url)
        label = find(s, '贴子含AI内容', root)
        state = p.ui.call('checkbox', key=label['parent'], expected_url=url)
    if state.get('checked') is not True: raise NativeStopped('贴吧AI内容声明未选定，未提交')
    return find(s, '发布', root, ('Text','Button'))


def prepare_article(p, account, binding, payload, target):
    platform = account['platform']; title = payload['title']; body = payload['body']
    if platform not in ('zhihu','juejin','tieba'): raise NativeStopped('此平台未实现本机文字文章准备')
    if '```' in body or re.search(r'<(?:iframe|script|img|video)\b', body, re.I):
        raise NativeStopped('本机执行器仅支持文字文章；复杂嵌入请使用网页发布')
    if platform == 'zhihu' and not payload.get('platform_tags'): raise NativeStopped('请为知乎文章配置相关话题')
    resumed=p.ui.resume_article(payload) if hasattr(p.ui,'resume_article') else None
    if resumed:s=resumed
    else:
        p.ui.call('open', url=compose_url(platform, target)); s = editor(p)
    url = s['url']
    if platform == 'tieba' and not any(n.get('id') == 'tb-editor-title' for n in s['nodes']):
        choices = [n for n in visible(s) if n.get('name') == '发贴' and n['type'] == 'Text']
        if not choices: raise NativeStopped('贴吧发贴入口未核对，未提交')
        for index,choice in enumerate(choices):
            fresh=p._snapshot(url)
            node=next((n for n in visible(fresh) if n['key']==choice['key'] and n.get('name')=='发贴'),None)
            if not node:raise NativeStopped('贴吧发贴入口发生变化，未提交')
            try:
                p._click(node,url);break
            except NativeStopped as ex:
                # The board has both a global and an inline composer entry.
                # Only an explicitly occluded, unclicked entry permits another.
                if '其他窗口遮挡目标控件' not in str(ex) or index==len(choices)-1:raise
        s = p._snapshot(url)
    title_node, body_node = fields(s, platform)
    old_title,old_body=copy(p,title_node,url),copy(p,body_node,url)
    if resumed:
        for _ in range(3):
            if normalized(old_title)==normalized(title) and normalized(old_body) in ('',normalized(body)):break
            p.sleep(.5);s=editor(p);url=s['url'];title_node,body_node=fields(s,platform)
            old_title,old_body=copy(p,title_node,url),copy(p,body_node,url)
    if (normalized(old_title) or normalized(old_body)) and (not resumed or normalized(old_title)!=normalized(title) or normalized(old_body) not in ('',normalized(body))):
        if resumed and hasattr(p.ui,'record_editor_mismatch'):p.ui.record_editor_mismatch(payload,old_title,old_body)
        raise NativeStopped('文章编辑器已有内容，已保留原稿，未提交')
    if hasattr(p.ui,'mark_draft'):p.ui.mark_draft(payload)
    if not normalized(old_title):paste(p, title_node, url, title)
    s = editor(p); url = s['url']
    title_node, body_node = fields(s, platform)
    if not normalized(old_body):paste(p, body_node, url, body)
    s = editor(p); url = s['url']
    submit = _zhihu(p,s,url,payload) if platform == 'zhihu' else _juejin(p,s,url,payload,target) if platform == 'juejin' else _tieba(p,s,url,payload,target)
    s = p._snapshot(url); title_node, body_node = fields(s, platform)
    if normalized(copy(p,title_node,url)) != normalized(title) or normalized(copy(p,body_node,url)) != normalized(body):
        raise NativeStopped('提交前文章标题或完整正文改变，未提交')
    s = p._snapshot(url)
    submit = find(s, submit['name'], types=(submit['type'],)) if platform != 'tieba' else _tieba(p,s,url,payload,target)
    return {'url':url,'submit':submit,'title':title,'body':body,'kind':'thread'}


def author_scope(s, binding, body):
    expected = {profile_key(u) for u in [binding['profile_url'], *binding.get('profile_aliases', [])]}
    by = {n['key']: n for n in s['nodes']}
    paragraphs = [rendered(x) for x in body.split('\n') if len(rendered(x)) >= 20]
    proofs = [n for n in s['nodes'] if n['type'] == 'Text' and rendered(n.get('name','')) in paragraphs]
    for proof in proofs:
        key = proof.get('parent'); seen = set()
        while key and key not in seen:
            seen.add(key)
            links = [n for n in s['nodes'] if n['type'] == 'Hyperlink' and n.get('visible') and inside(s,n['key'],key)]
            profiles = {profile_key(n.get('value','')) for n in links
                        if re.search(r'https://(?:www\.zhihu\.com/people/|juejin\.cn/user/|tieba\.baidu\.com/home/main\?)',n.get('value',''))}
            if profiles:
                if profiles <= expected:
                    return next(n['value'] for n in links if profile_key(n.get('value','')) in expected)
                break
            key = by.get(key,{}).get('parent')
    return None


def verify_article(p, account, binding, payload):
    platform = account['platform']
    from .registry import juejin_article_result_url
    result_url=lambda value:juejin_article_result_url(value) if platform=='juejin' else thread_url(platform,value)
    for _ in range(p.poll_attempts):
        p.sleep(1)
        try:
            s = p.ui.call('follow_published')
            try: url = result_url(s['url'])
            except ValueError:
                links = []
                for n in visible(s):
                    if n['type'] != 'Hyperlink' or normalized(payload['title']) not in normalized(n.get('name')):continue
                    try: links.append(result_url(n.get('value','')))
                    except ValueError:pass
                links = list(dict.fromkeys(links))
                if len(links)==1:
                    if hasattr(p.ui,'open_receipt'):p.ui.open_receipt(links[0],payload['title'])
                    else:p.ui.call('open',url=links[0])
                    s=p.ui.call('follow_published');url=result_url(s['url'])
                else:continue
            text = rendered(s['text'])
            docs=[n for n in s['nodes'] if n['type']=='Document']
            semantic=rendered(semantic_value(s,docs[0]['key'],s['text'],strict=False)) if len(docs)==1 else text
            wanted=re.findall(r'https?://[^\s\u200b\ufeff\ufffc，。！？、<>"“”]+',payload['body'])
            destinations={link_destination(n.get('value','')) for n in s['nodes'] if n['type']=='Hyperlink'}
            if any(url not in destinations for url in wanted):continue
            if rendered(payload['title']) not in text:continue
            if not all(rendered(para) in text or rendered(para) in semantic for para in payload['body'].split('\n') if rendered(para)):continue
            author = author_scope(s,binding,payload['body'])
            if author:
                return {'url':url,'post_id':url.rsplit('/',1)[-1], 'visibility':'account_visible',
                        'author_url':author,'author_name':binding['name'],'title':payload['title'],'body':payload['body']}
        except Exception:
            pass
    raise NativeUnknown('文章提交后无法核对原账号与完整正文，只允许核验，不得重发')
