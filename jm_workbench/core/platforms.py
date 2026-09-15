"""Capabilities are explicit; a crawler never implies a comment publisher."""
PLATFORMS = {
    'ks': {'name': '快手', 'home': 'https://www.kuaishou.com/', 'comment': True},
    'dy': {'name': '抖音', 'home': 'https://www.douyin.com/', 'comment': False},
    'xhs': {'name': '小红书', 'home': 'https://www.xiaohongshu.com/', 'comment': False},
    'bili': {'name': '哔哩哔哩', 'home': 'https://www.bilibili.com/', 'comment': False},
    'wb': {'name': '微博', 'home': 'https://weibo.com/', 'comment': False},
    'tieba': {'name': '百度贴吧', 'home': 'https://tieba.baidu.com/', 'comment': False},
    'zhihu': {'name': '知乎', 'home': 'https://www.zhihu.com/', 'comment': False},
}
