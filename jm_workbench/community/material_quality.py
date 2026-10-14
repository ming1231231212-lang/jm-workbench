"""Deterministic gates for generated material; model output is untrusted data."""
import re
from difflib import SequenceMatcher
from .models import DailyTopic,ReplyMaterial
from .registry import thread_url

AD=re.compile(r'网盘|代充|返佣|加群|加微|私信|破解版|购买链接|抽奖|点赞关注|互赞|互评',re.I)
INJECTION=re.compile(r'ignore (?:all |previous )?instructions|system prompt|忽略.{0,8}(?:指令|规则)|泄露.{0,8}(?:密钥|密码)',re.I)
def compact(value):
    value=re.sub(r'[（(]?AI\s*辅助(?:整理|创作)?[）)]?','',value,flags=re.I)
    return ''.join(c for c in value.casefold() if c.isalnum())
def similar(a,b):
    a,b=compact(a),compact(b)
    if not a or not b:return False
    return a==b or SequenceMatcher(None,a,b,autojunk=False).ratio()>=.82
def grams(value):
    value=compact(value)
    return {value[i:i+2] for i in range(max(0,len(value)-1))}
def rank_candidates(candidates,terms,now):
    rows=[];seen=set()
    for c in candidates:
        text=c.get('title','')+'\n'+c.get('excerpt','')
        if len(c.get('excerpt',''))<45 or AD.search(text) or INJECTION.search(text):continue
        match=compact(text)
        if not any(compact(t) in match or (t.casefold()=='chatgpt' and 'gpt' in match) for t in terms):continue
        age=now-c.get('activity_at',0)
        if not c.get('activity_evidence') or not -3600<=age<=30*86400:continue
        heat=c.get('heat',0) if c.get('heat_evidence') else 0
        if age>7*86400 and heat<3:continue
        if c['url'] in seen:continue
        seen.add(c['url']);rows.append(c)
    return sorted(rows,key=lambda c:(-(c.get('heat',0) if c.get('heat_evidence') else 0),-c.get('activity_at',0)))

def validate_generated(data,platform,candidates,history,used_targets,need_article=True):
    sources={c['url']:c for c in candidates};accepted=[];bodies=list(history);targets=set(used_targets)
    article=None
    if need_article:
        raw=data.get('article')
        if not isinstance(raw,dict):raise ValueError('模型未准备文章')
        article=DailyTopic.model_validate(raw).model_dump()
        if not 250<=len(article['body'])<=2000 or (platform=='tieba' and len(article['title'])>31):raise ValueError('文章长度不合适')
        if not re.search(r'AI\s*辅助',article['body']) or 'quzaoai.com' not in article['body']:raise ValueError('文章缺少AI说明或网站介绍')
        if AD.search(article['body']) or INJECTION.search(article['body']):raise ValueError('文章有不合适的推广或指令文本')
        urls=re.findall(r'https?://[^\s<>，。；）)]+',article['body'])
        if any(u.rstrip('/')!='https://quzaoai.com' for u in urls):raise ValueError('文章出现未授权链接')
        if platform=='juejin' and urls:raise ValueError('掘金文章使用文字域名')
        if any(similar(article['body'],b) for b in bodies):raise ValueError('文章与历史内容过于相似')
        if platform in ('juejin','zhihu') and not article['platform_tags']:raise ValueError('文章缺少相关话题')
        bodies.append(article['body'])
    replies=data.get('replies',[])
    if not isinstance(replies,list) or len(replies)>5:raise ValueError('评论结果格式不正确')
    for raw in replies:
        url=thread_url(platform,raw.get('source_url',''));source=sources.get(url)
        if not source or url in targets:raise ValueError('评论原帖不存在或已经接触')
        anchor=raw.get('anchor','').strip();body=raw.get('body','').strip()
        if len(compact(anchor))<8 or compact(anchor) not in compact(source['excerpt']):raise ValueError('评论缺少真实原文依据')
        if not grams(anchor)&grams(body) or len(grams(source['excerpt'])&grams(body))<3:raise ValueError('评论没有回应原帖的具体内容')
        if not 40<=len(body)<=500 or not re.search(r'AI\s*辅助',body):raise ValueError('评论长度或AI声明不合适')
        if AD.search(body) or INJECTION.search(body) or re.search(r'https?://|www\.|\.(?:com|cn|net|org)\b',body,re.I):raise ValueError('自动评论不放广告或外链')
        if any(similar(body,b) for b in bodies):raise ValueError('评论与历史内容过于相似')
        row=ReplyMaterial(url=url,title=source['title'],excerpt=source['excerpt'],body=body,keyword='相关活跃讨论',source_tags=[]).model_dump()
        accepted.append(row);bodies.append(body);targets.add(url)
    return {'article':article,'replies':accepted}
