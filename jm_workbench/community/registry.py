"""Capabilities are explicit; a website URL alone is not an automatic adapter."""
import re
from urllib.parse import quote, urlparse

_ROWS = [
    ('zhihu','知乎','国内','AI应用 互联网 职场','web','https://www.zhihu.com/','https://zhuanlan.zhihu.com/write','专栏文章 / 文章和回答下的网页评论','',100),
    ('tieba','百度贴吧','国内','AI 互联网 综合兴趣','browser','https://tieba.baidu.com/','https://tieba.baidu.com/','文字主题帖 / 顶层评论（正文≤2000字）','吧名，如人工智能；名称本身带“吧”字时保留',31),
    ('xiaohongshu','小红书','国内','AI工具 效率 生活','web','https://www.xiaohongshu.com/','https://creator.xiaohongshu.com/publish/publish','笔记','',20),
    ('csdn','CSDN','国内','AI开发 编程 技术','browser','https://www.csdn.net/','https://editor.csdn.net/md/','技术文章 / 顶层评论','文章填博客；评论填写文章HTTPS链接',100),
    ('juejin','稀土掘金','国内','AI编程 互联网 开发','browser','https://juejin.cn/','https://juejin.cn/editor/drafts/new?v=2','技术文章 / 顶层评论','文章分类，如人工智能；评论填写文章HTTPS链接',100),
    ('v2ex','V2EX','国内','互联网 AI 独立开发','web','https://www.v2ex.com/','https://www.v2ex.com/new','主题帖','节点名（可选）',120),
    ('bilibili','哔哩哔哩','国内','AI教程 科技 内容创作','web','https://www.bilibili.com/','https://t.bilibili.com/','动态/图文','',100),
    ('weibo','微博','国内','AI资讯 互联网 科技','web','https://weibo.com/','https://weibo.com/','微博','',120),
    ('wechat_mp','微信公众号','国内','AI应用 互联网 个人创作','web','https://mp.weixin.qq.com/','https://mp.weixin.qq.com/','公众号图文','',120),
    ('oschina','OSCHINA','国内','开源 AI工程 编程','web','https://www.oschina.net/','https://my.oschina.net/','博客/讨论','',120),
    ('segmentfault','SegmentFault 思否','国内','AI开发 编程 技术问答','web','https://segmentfault.com/','https://segmentfault.com/write','文章/问答','',120),
    ('reddit','Reddit','国外','AI 互联网 创业 综合兴趣','api','https://www.reddit.com/','https://www.reddit.com/submit','文字主题帖','Subreddit 名称，不带 r/',120),
    ('x','X','国外','AI 科技 互联网 创业','api','https://x.com/','https://x.com/compose/post','短帖','',120),
    ('quora','Quora','国外','AI应用 互联网 知识','web','https://www.quora.com/','https://www.quora.com/','问答/Space','',120),
    ('linkedin','LinkedIn','国外','企业AI 职场 互联网 创业','web','https://www.linkedin.com/','https://www.linkedin.com/feed/','动态/文章','',120),
    ('producthunt','Product Hunt','国外','AI工具 产品 SaaS 创业','web','https://www.producthunt.com/','https://www.producthunt.com/posts/new','产品/产品论坛','',120),
    ('hackernews','Hacker News','国外','AI技术 编程 互联网 创业','manual','https://news.ycombinator.com/','https://news.ycombinator.com/submit','本人撰写的主题帖','',80),
    ('dev','DEV Community','国外','AI编程 编程 开源','api','https://dev.to/','https://dev.to/new','Markdown文章','',120),
    ('medium','Medium','国外','AI 科技 互联网 创业','web','https://medium.com/','https://medium.com/new-story','文章','',120),
    ('huggingface','Hugging Face','国外','AI 大模型 开源','api','https://huggingface.co/','https://discuss.huggingface.co/','Hub项目讨论（不是论坛主题）','模型：owner/repo；数据集：datasets/owner/repo；应用：spaces/owner/repo',120),
    ('indiehackers','Indie Hackers','国外','AI产品 独立开发 SaaS 创业','web','https://www.indiehackers.com/','https://www.indiehackers.com/','帖子','',120),
]
MODES = {'api':'API发布 · 需授权','browser':'浏览器发布 · 需登录核验','web':'网页发布 · 暂无自动适配','manual':'仅本人网页发布'}
PLATFORMS = {r[0]: dict(zip(('id','name','region','categories','mode','home','compose','format','destination_hint','title_limit'),r)) for r in _ROWS}
for p in PLATFORMS.values():
    p.update(mode_label=MODES[p['mode']], automatic=p['mode'] in ('api','browser'), verification='适配器模拟测试；真实发帖未验收')
    p['capabilities']={'local_draft':True,'open_website':True,'record_link':True,
        'auto_publish':p['automatic'],'auto_comment':p['id'] in ('tieba','juejin','csdn'),
        'comment_draft':p['id'] in ('tieba','juejin','csdn','zhihu'),
        'web_comment':p['id'] in ('tieba','juejin','csdn','zhihu'),
        'daily_plan':p['id'] in ('tieba','juejin','csdn'),'export_content':True}
    p['note'] = ('禁止自动发帖和AI生成/改写文字，请本人撰写并在网站提交。' if p['id']=='hackernews' else
                 '账号需具备API权限；仅保存密钥不代表可以发布。' if p['mode']=='api' else
                 '依赖网站编辑器；验证码或页面变化会暂停，不绕过限制。' if p['mode']=='browser' else
                 '工作台管理草稿、打开账号网页、复制内容、登记链接；最终在网站提交。')
    if p['id']=='wechat_mp':
        p['note']='支持本地草稿、导出排版、打开公众平台与登记文章链接。当前需在公众平台完成发布；个人号不默认具备接口发布权限。'
    if p['id']=='zhihu':
        p['note']='支持专栏文章、文章和回答下的网页评论；使用日常Chrome提交后登记链接。自动发布与每日计划未启用。'
        p['verification']='网页交接流程测试；实际发布与公开可见性未验收'


def platform(ident):
    if ident not in PLATFORMS:
        raise ValueError('不支持的社区平台')
    return PLATFORMS[ident]


def publication_platform(config, ident):
    """Runtime availability is separate from installed adapter capabilities."""
    p=platform(ident)
    if config.values.get('community_browser_execution')=='native' and ident in ('tieba','juejin','zhihu'):
        return {**p,'automatic':True,'mode':'native','mode_label':'本机Chrome发布 · 需核验账号',
                'note':'使用日常Chrome与本人主页核验。需要电脑保持唤醒且桌面可交互；遇到验证或结果不明停止，不会自动重发。',
                'verification':'原生页面逐项核对与隔离模拟测试；公开可见性另行核验',
                'capabilities':{**p['capabilities'],'auto_publish':True,'auto_comment':True,'daily_plan':True}}
    if config.values.get('community_browser_execution')=='native' and p['mode']=='browser':
        return {**p,'automatic':False,'mode':'web','mode_label':'网页发布',
                'capabilities':{**p['capabilities'],'auto_publish':False,'auto_comment':False,'daily_plan':False}}
    if p['mode']!='browser' or config.values.get('community_browser_execution')!='web':return p
    return {**p,'automatic':False,'mode':'web','mode_label':'网页发布 · 自动控制已停用',
            'note':'浏览器扩展已取消。复制或导出正文，在日常 Chrome 提交，再登记链接；自动发帖、评论和每日计划已停用。',
            'capabilities':{**p['capabilities'],'auto_publish':False,'auto_comment':False,'daily_plan':False}}


def destination(platform_id, value):
    value = value.strip()
    if platform_id == 'zhihu' and value:
        raise ValueError('知乎专栏文章无需填写板块；评论请使用原帖文章或回答链接')
    if platform_id == 'tieba' and (not value or len(value)>50 or re.search(r'[\x00-\x1f<>]', value)):
        raise ValueError('请填写有效的贴吧吧名/板块')
    if platform_id == 'juejin' and value not in ('人工智能','开发工具','前端','后端','Android','iOS','代码人生','阅读'):
        raise ValueError('请选择掘金有效的文章分类')
    if platform_id == 'csdn' and value not in ('', '博客'):
        raise ValueError('CSDN当前发布到个人博客，请填写博客')
    if platform_id == 'reddit' and not re.fullmatch(r'[A-Za-z0-9_]{2,30}', value):
        raise ValueError('请填写有效的Reddit社区名称，不带r/')
    if platform_id == 'huggingface' and not re.fullmatch(r'(?:(?:datasets|spaces)/)?[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value):
        raise ValueError('请填写有效的Hub项目板块：owner/repo')
    if platform_id == 'v2ex' and value and not re.fullmatch(r'[A-Za-z0-9_]{1,60}', value):
        raise ValueError('V2EX节点名无效')
    return value


def compose_url(platform_id, target=''):
    p = platform(platform_id)
    if platform_id=='zhihu' and target:
        return thread_url(platform_id,target)
    if platform_id=='tieba' and target:
        if target.startswith('https://'):
            return tieba_thread_url(target)
        return 'https://tieba.baidu.com/f?kw='+quote(destination(platform_id,target))
    if platform_id=='juejin' and target.startswith('https://'):
        return juejin_thread_url(target)
    if platform_id=='csdn' and target.startswith('https://'):
        return csdn_thread_url(target)
    if platform_id=='reddit' and target:
        return 'https://www.reddit.com/r/'+destination(platform_id,target)+'/submit'
    if platform_id=='v2ex' and target:
        return 'https://www.v2ex.com/new/'+destination(platform_id,target)
    return p['compose']


def tieba_thread_url(value):
    parsed=urlparse(value.strip())
    if (parsed.scheme!='https' or parsed.hostname!='tieba.baidu.com' or parsed.username or
        parsed.password or parsed.port not in (None,443) or not re.fullmatch(r'/p/[1-9][0-9]{3,19}',parsed.path)):
        raise ValueError('请填写百度贴吧主题帖HTTPS链接，如 https://tieba.baidu.com/p/123456')
    return 'https://tieba.baidu.com'+parsed.path


def safe_post_url(platform_id, value):
    parsed=urlparse(value)
    domains={urlparse(platform(platform_id)['home']).hostname, urlparse(platform(platform_id)['compose']).hostname}
    extras={'zhihu':{'zhuanlan.zhihu.com'},'csdn':{'blog.csdn.net'},'bilibili':{'www.bilibili.com','t.bilibili.com'},'x':{'x.com','www.x.com','twitter.com'},'huggingface':{'huggingface.co','discuss.huggingface.co'}}
    domains |= extras.get(platform_id,set())
    if parsed.scheme!='https' or parsed.hostname not in domains or parsed.username or parsed.password or parsed.port not in (None,443) or len(value)>2000:
        raise ValueError('请填写该平台的HTTPS帖子链接')
    return value


def juejin_thread_url(value):
    parsed=urlparse(value.strip())
    if (parsed.scheme!='https' or parsed.hostname!='juejin.cn' or parsed.username or parsed.password or
        parsed.port not in (None,443) or not re.fullmatch(r'/post/[1-9][0-9]{10,23}',parsed.path)):
        raise ValueError('请填写掘金文章HTTPS链接，如 https://juejin.cn/post/1234567890123456789')
    return 'https://juejin.cn'+parsed.path


def juejin_article_result_url(value):
    """Accept an observed publication result, including Juejin's /spost link.

    Comment targets still require the ordinary /post route.
    """
    parsed=urlparse(value.strip())
    if (parsed.scheme!='https' or parsed.hostname!='juejin.cn' or parsed.username or parsed.password or
        parsed.port not in (None,443) or not re.fullmatch(r'/(?:post|spost)/[1-9][0-9]{10,23}',parsed.path)):
        raise ValueError('掘金文章回执链接无效')
    return 'https://juejin.cn'+parsed.path


def csdn_thread_url(value):
    parsed=urlparse(value.strip())
    if (parsed.scheme!='https' or parsed.hostname!='blog.csdn.net' or parsed.username or parsed.password or
        parsed.port not in (None,443) or not re.fullmatch(r'/[A-Za-z0-9_-]{2,100}/article/details/[1-9][0-9]{3,23}',parsed.path)):
        raise ValueError('请填写CSDN文章HTTPS链接，如 https://blog.csdn.net/author/article/details/123456789')
    return 'https://blog.csdn.net'+parsed.path


def thread_url(platform_id,value):
    if platform_id=='tieba':return tieba_thread_url(value)
    if platform_id=='juejin':return juejin_thread_url(value)
    if platform_id=='csdn':return csdn_thread_url(value)
    if platform_id=='zhihu':
        from .zhihu import comment_target_url
        return comment_target_url(value)
    raise ValueError('此平台尚未支持评论')


def reply_target_key(platform_id,value):
    if platform_id=='zhihu':
        from .zhihu import comment_target_key
        return comment_target_key(value)
    return thread_url(platform_id,value)


def tag_label(value):
    if not re.fullmatch(r'[\w +.#-]{1,30}',value,flags=re.UNICODE):
        raise ValueError('标签需1–30字，不得包含链接或路径')
    return value
