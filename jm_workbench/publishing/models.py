from typing import Literal
from pydantic import Field, field_validator, model_validator
from ..core.models import Strict


PLATFORMS = {
    'xhs': {'name': '小红书', 'type': 1},
    'tencent': {'name': '视频号', 'type': 2},
    'dy': {'name': '抖音', 'type': 3},
    'ks': {'name': '快手', 'type': 4},
}
MAX_UPLOAD = 150 * 1024 * 1024


class PublishInput(Strict):
    request_id: str = Field(min_length=8, max_length=80, pattern=r'^[\w-]+$')
    title: str = Field(min_length=1, max_length=80)
    material_ids: list[str] = Field(min_length=1, max_length=10)
    account_ids: list[str] = Field(min_length=1, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=10)
    mode: Literal['now', 'scheduled'] = 'now'
    schedule_at: float = Field(default=0, ge=0, allow_inf_nan=False)
    platform_draft: bool = False
    product_link: str = Field(default='', max_length=500)
    product_title: str = Field(default='', max_length=60)

    @field_validator('tags')
    @classmethod
    def valid_tags(cls, tags):
        cleaned = list(dict.fromkeys(t.strip().lstrip('#') for t in tags))
        if any(not t or len(t) > 30 or any(c in t for c in '\n\r\x00') for t in cleaned):
            raise ValueError('话题长度1至30字，每项一个话题')
        return cleaned

    @model_validator(mode='after')
    def valid(self):
        self.material_ids = list(dict.fromkeys(self.material_ids))
        self.account_ids = list(dict.fromkeys(self.account_ids))
        if self.mode == 'scheduled' and not self.schedule_at:
            raise ValueError('请选择定时发布时间')
        if any(c in self.title for c in '\r\n\x00'):
            raise ValueError('标题不能包含换行或控制字符')
        if self.product_link:
            from urllib.parse import urlparse
            u = urlparse(self.product_link)
            if u.scheme != 'https' or not u.hostname or u.username or u.password:
                raise ValueError('商品链接必须为有效的 HTTPS 地址')
        return self


class PublishingSettings(Strict):
    sau_root: str = Field(default=r'D:\SocialAutoUpload', max_length=500)
    sau_url: str = Field(default='http://127.0.0.1:5409', max_length=120)
    sau_web_url: str = Field(default='http://127.0.0.1:5173', max_length=120)
    publish_gap_minutes: int = Field(default=30, ge=1, le=1440)
    publish_daily_limit: int = Field(default=5, ge=1, le=20)

    @field_validator('sau_url', 'sau_web_url')
    @classmethod
    def loopback(cls, value):
        from urllib.parse import urlparse
        u = urlparse(value)
        try:
            port = u.port
        except ValueError:
            raise ValueError('本机服务端口无效')
        if u.scheme != 'http' or u.hostname not in ('127.0.0.1', 'localhost') or u.username or u.password or u.path not in ('', '/') or u.query or u.fragment or not port or not 1024 <= port <= 65535:
            raise ValueError('只允许指定端口的本机 HTTP 服务地址')
        return f'http://127.0.0.1:{port}'


class ResolveInput(Strict):
    outcome: Literal['submitted', 'not_sent']
    note: str = Field(min_length=12, max_length=300)
