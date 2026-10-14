"""Read public list cards and original text through the existing local Chrome UI.

Only a dedicated discovery tab is navigated. Search snippets never become original
text; incomplete/ambiguous reads are discarded rather than sent to the publisher.
"""
import re
import time
from difflib import SequenceMatcher
from datetime import datetime,timedelta,timezone
from urllib.parse import urlencode,urlsplit,parse_qsl
from .registry import thread_url,compose_url
from .native import NativeStopped,normalized
from .material_quality import AD,INJECTION,rank_candidates

TZ=timezone(timedelta(hours=8))
def activity(text,now):
    local=datetime.fromtimestamp(now,TZ)
    for pattern,factor in [(r'(\d+)\s*分钟前',60),(r'(\d+)\s*小时前',3600),(r'(\d+)\s*天前',86400)]:
        m=re.search(pattern,text)
        if m:return now-int(m[1])*factor,m[0]
    if '刚刚' in text:return now,'刚刚'
    m=re.search(r'(?<!\d)(20\d\d)[-年](\d{1,2})[-月](\d{1,2})',text)
    if m:
        try:return datetime(*map(int,m.groups()),tzinfo=TZ).timestamp(),m[0]
        except ValueError:return 0,''
    m=re.search(r'(?<![\d-])(\d{2})-(\d{2})(?!\d)',text)
    if m:
        try:
            day=datetime(local.year,int(m[1]),int(m[2]),tzinfo=TZ)
            if day>local+timedelta(days=1):day=day.replace(year=day.year-1)
            return day.timestamp(),m[0]
        except ValueError:pass
    return 0,''

def card_text(nodes,node,platform):
    if platform=='tieba':return node['name']
    by={n['key']:n for n in nodes};cur=node
    for _ in range(7):
        cur=by.get(cur.get('parent'),{})
        if cur.get('type')=='ListItem':return cur.get('name','')
        if cur.get('type')=='Document':break
    return ''

def list_candidates(snapshot,platform,now):
    result=[];seen=set()
    for node in snapshot.get('nodes',[]):
        if node.get('type')!='Hyperlink' or len(node.get('name',''))<6:continue
        try:url=thread_url(platform,node.get('value',''))
        except ValueError:continue
        if platform=='zhihu' and not url.startswith('https://zhuanlan.zhihu.com/p/'):continue
        if url in seen:continue
        seen.add(url);card=card_text(snapshot['nodes'],node,platform)
        if not card or AD.search(card) or INJECTION.search(card) or '趣造AI' in card:continue
        at,evidence=activity(card,now)
        m=re.search(r'赞同\s*(\d+)|(?:评论|回复)\s*(\d+)',card)
        heat=int(next(g for g in m.groups() if g is not None)) if m else 0
        result.append({'url':url,'title_hint':node['name'] if platform!='tieba' else '', 'card':card[:1600],'activity_at':at,'activity_evidence':evidence,
            'heat':heat,'heat_evidence':m[0] if m else '', 'list_url':snapshot['url']})
    return result

def original(snapshot,platform,candidate,now,own_profiles=()):
    url=thread_url(platform,snapshot.get('url',''))
    if url!=candidate['url']:raise ValueError('原帖地址不一致')
    doc=next((n for n in snapshot.get('nodes',[]) if n.get('type')=='Document'),{})
    title=doc.get('name','')
    title=re.sub(r'^\([^)]*(?:私信|消息)[^)]*\)\s*','',title)
    title=re.sub(r'\s*-\s*(?:百度贴吧|掘金|知乎)$','',title).strip()
    text=snapshot.get('text','')
    hint=candidate.get('title_hint','')
    if platform=='juejin':
        headings=[n['name'] for n in snapshot.get('nodes',[]) if n.get('type')=='Text' and 5<=len(n.get('name',''))<=200 and normalized(title).startswith(normalized(n['name'])) and n['name'] in text]
        if headings:title=max(headings,key=len)
        if title not in text and hint:
            # Chrome may translate a heading while retaining the SEO document title.
            # Restrict to the original header above its first publication date.
            header=re.split(r'20\d\d-\d\d-\d\d',text,1)[0][-650:]
            options=[line.strip() for line in header.splitlines() if 5<=len(line.strip())<=200]
            scored=[(SequenceMatcher(None,normalized(hint),normalized(line)).ratio(),line) for line in options]
            if scored and max(scored)[0]>=.6:title=max(scored)[1]
    if not 5<=len(title)<=200 or title not in text:raise ValueError('未取得原帖标题')
    # All stop markers are below the original article, before comments/sidebar.
    start=text.find(title)
    if platform=='zhihu':
        second=text.find(title,start+len(title))
        if 0<=second-start<450:start=second
    text=text[start+len(title):]
    stops={'tieba':['\n转发\n','\n全部回复','\n说两句'],
        'juejin':['\n评论\n','\n相关推荐','\n本文收录于'],
        'zhihu':['\n所属专栏','\n文章被以下专栏收录','\n推荐阅读','\n赞同\n','\n评论\n']}[platform]
    for stop in stops:text=text.split(stop,1)[0]
    if platform=='juejin':text=re.split(r'\n评论\s*\d+\s*\n',text,1)[0]
    if len(text.strip())<45:raise ValueError('原帖正文不足')
    excerpt=text.strip()[:2200]
    if any(p and p in [n.get('value') for n in snapshot.get('nodes',[]) if n.get('type')=='Hyperlink' and n.get('name') in ('趣造AI','齐家明')] for p in own_profiles):
        raise ValueError('排除自己的原帖')
    row={**candidate,'url':url,'title':title,'excerpt':excerpt,'read_at':now}
    if platform=='juejin':
        at,evidence=activity(text[:300],now)
        row.update(activity_at=at,activity_evidence=evidence)
    elif not row['activity_at']:
        at,evidence=activity(text[:200],now);row.update(activity_at=at,activity_evidence=evidence)
    return row

class NativeDiscovery:
    def __init__(self,channel,clock=time.time,sleep=time.sleep):
        self.ui,self.clock,self.sleep=channel,clock,sleep;self.replaced=False
    def read(self,url):
        if self.clock()>getattr(self,'deadline',float('inf')):raise NativeStopped('本轮读取时间已到，保留已核验的候选')
        try:self.ui.call('open',url=url)
        except NativeStopped:
            # Read-only discovery can replace its closed/repurposed tab once.
            # Preserve the old tab and the verified everyday window binding.
            if self.replaced or not hasattr(self.ui,'state') or self.ui.state.get('draft'):raise
            tabs=self.ui.raw('tabs')['tabs'];key=self.ui.state.get('key')
            exists=any(t['key']==key for t in tabs)
            if exists:
                self.ui.raw('select',key=key)
                if self.ui.raw('url')['url']==self.ui.state.get('url'):raise
            self.ui.state={k:self.ui.state[k] for k in ('window','process_id','process_started') if k in self.ui.state}
            if len(self.ui.state)!=3:raise NativeStopped('发现页缺少日常Chrome窗口绑定')
            self.ui.expected='';self.ui.save();self.replaced=True
            self.ui.call('open',url=url)
        for _ in range(5):
            if self.clock()>getattr(self,'deadline',float('inf')):break
            self.sleep(.6)
            try:s=self.ui.call('snapshot')
            except NativeStopped:continue # Read-only UIA may be transient while navigating.
            a,b=urlsplit(s.get('url','')),urlsplit(url)
            if (a.scheme,a.netloc,a.path,sorted(parse_qsl(a.query)))!=(b.scheme,b.netloc,b.path,sorted(parse_qsl(b.query))):continue
            if len(s.get('text',''))>150:return s
        raise NativeStopped('原帖或搜索页尚未完整加载；没有使用其他页面')
    def discover(self,account,terms):
        platform=account['platform'];now=self.clock();seed=account.get('_discovery_round',0)
        self.deadline=now+210
        excluded=set(account.get('_discovery_exclude',[]));links=[];seen=set()
        if platform=='tieba':
            boards=account.get('_discovery_boards') or ['ai工具','chatgpt','人工智能']
            urls=[compose_url('tieba',b) for b in boards[:3]]
        elif platform=='juejin':urls=['https://juejin.cn/ai?sort=newest']
        else:
            terms=terms or ['AI工具','AI工作流','AI编程']
            rotated=terms[seed%len(terms):]+terms[:seed%len(terms)]
            urls=['https://www.zhihu.com/search?'+urlencode({'type':'content','q':t}) for t in rotated[:3]]
        for url in urls:
            if self.clock()>now+75 and links:break # Leave time to verify originals.
            s=self.read(url)
            for page in range(2):
                for c in list_candidates(s,platform,now):
                    if c['url'] not in seen and c['url'] not in excluded:
                        seen.add(c['url']);links.append(c)
                if page==1:break
                self.ui.call('read-more',expected_url=url);self.sleep(.6);s=self.ui.call('snapshot')
                a,b=urlsplit(s.get('url','')),urlsplit(url)
                if (a.netloc,a.path,sorted(parse_qsl(a.query)))!=(b.netloc,b.path,sorted(parse_qsl(b.query))):raise NativeStopped('列表地址已变化，未继续读取')
        # Rotate the candidates on a retry to avoid repeatedly testing one poor batch.
        links=sorted(links,key=lambda c:(-c['activity_at'],-c['heat']))
        offset=(seed*8)%len(links) if links else 0;links=links[offset:]+links[:offset]
        rows=[]
        binding=account.get('native_binding',{});profiles=[binding.get('profile_url',''),*binding.get('profile_aliases',[])]
        for c in links[:10]:
            if self.clock()>self.deadline:break
            try:
                row=original(self.read(c['url']),platform,c,self.clock(),profiles)
                rows.extend(rank_candidates([row],terms,self.clock()))
            except (NativeStopped,ValueError):continue
            if len(rows)>=7:break
        return rank_candidates(rows,terms,self.clock())
