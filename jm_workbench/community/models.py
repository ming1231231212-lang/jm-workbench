import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from .registry import platform


class CommunityAccount(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1,max_length=60)
    platform: str
    identity_hint: str = Field(default='',max_length=100)
    secret: SecretStr = Field(default=SecretStr(''), max_length=4096)
    enabled: bool = True

    @field_validator('platform')
    @classmethod
    def valid_platform(cls, value):
        platform(value)
        return value


class Target(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)
    account_id: str = Field(min_length=1,max_length=64,pattern=r'^[A-Za-z0-9_-]+$')
    destination: str = Field(default='',max_length=200)


class CommunityPost(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)
    request_id: str = Field(min_length=8,max_length=80,pattern=r'^[A-Za-z0-9_-]+$')
    title: str = Field(min_length=1,max_length=120)
    body: str = Field(min_length=1,max_length=12000)
    tags: list[str] = Field(default_factory=list,max_length=4)
    targets: list[Target] = Field(min_length=1,max_length=20)
    schedule_at: float = 0
    kind: Literal['thread','reply'] = 'thread'
    category: str = Field(default='',max_length=30)
    platform_tags: list[str] = Field(default_factory=list,max_length=3)
    source_title: str = Field(default='',max_length=200)
    source_excerpt: str = Field(default='',max_length=6000)

    @field_validator('platform_tags')
    @classmethod
    def platform_tags_valid(cls, values):
        from .registry import tag_label
        return list(dict.fromkeys(tag_label(v) for v in values))

    @field_validator('schedule_at')
    @classmethod
    def finite_schedule(cls, value):
        if not math.isfinite(value) or value<0:
            raise ValueError('定时时间无效')
        return value

    @field_validator('targets')
    @classmethod
    def unique_targets(cls, values):
        pairs=[(v.account_id,v.destination) for v in values]
        if len(pairs)!=len(set(pairs)):
            raise ValueError('发布目标重复')
        return values

    @field_validator('tags')
    @classmethod
    def tags_valid(cls, values):
        import re
        if any(not re.fullmatch(r'[a-zA-Z0-9]{1,30}',t) for t in values):
            raise ValueError('话题最多4个，仅使用英文字母或数字')
        return list(dict.fromkeys(values))


class LinkRecord(BaseModel):
    url: str = Field(min_length=10,max_length=2000)


class ResolveRecord(BaseModel):
    outcome: Literal['submitted','not_sent']
    note: str = Field(min_length=12,max_length=500)
    url: str = Field(default='',max_length=2000)


class ClearRecord(BaseModel):
    note: str = Field(min_length=12,max_length=500)


class DailyTopic(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    title: str = Field(min_length=5,max_length=100)
    body: str = Field(min_length=20,max_length=2000)
    keyword: str = Field(default='',max_length=60)
    platform_tags: list[str] = Field(default_factory=list,max_length=3)

    @field_validator('platform_tags')
    @classmethod
    def tags_valid(cls, values):
        from .registry import tag_label
        return list(dict.fromkeys(tag_label(v) for v in values))


class ReplyMaterial(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    url: str = Field(min_length=10,max_length=2000)
    title: str = Field(min_length=1,max_length=200)
    excerpt: str = Field(min_length=10,max_length=6000)
    body: str = Field(min_length=20,max_length=2000)
    keyword: str = Field(default='',max_length=60)
    source_tags: list[str] = Field(default_factory=list,max_length=3)

    @field_validator('url')
    @classmethod
    def valid_url(cls,value):
        from .registry import thread_url
        from urllib.parse import urlparse
        return thread_url('juejin' if urlparse(value).hostname=='juejin.cn' else 'tieba',value)


class ReplyRule(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    name: str = Field(min_length=1,max_length=60)
    terms: list[str] = Field(min_length=1,max_length=8)
    body: str = Field(min_length=30,max_length=1800)
    require_question: bool = True

    @field_validator('terms')
    @classmethod
    def valid_terms(cls,values):
        if any(len(v.strip())<2 or len(v)>40 for v in values):raise ValueError('匹配词需2–40字')
        return [v.strip() for v in values]

    @field_validator('body')
    @classmethod
    def no_advertising(cls,value):
        import re
        if re.search(r'https?://|www\.|\.(?:com|cn|net|org)\b|加[微Vv]|私信|加群|微信|VX',value,re.I):
            raise ValueError('自动匹配普通讨论帖的评论不得带网址或联系方式；推广仅使用指定入口素材')
        return value


class DailyPlan(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    name: str = Field(min_length=1,max_length=60)
    account_id: str = Field(min_length=1,max_length=64)
    board: str = Field(min_length=1,max_length=50)
    rules_note: str = Field(min_length=12,max_length=1000)
    hour: int = Field(default=10,ge=0,le=20)
    minute: int = Field(default=0,ge=0,le=59)
    topics: list[DailyTopic] = Field(default_factory=list,max_length=60)
    replies: list[ReplyMaterial] = Field(default_factory=list,max_length=100)
    reply_rules: list[ReplyRule] = Field(default_factory=list,max_length=60)
    source_boards: list[str] = Field(default_factory=list,max_length=3)

    @field_validator('board')
    @classmethod
    def valid_board(cls,value):
        from .registry import destination
        return destination('tieba',value)

    @field_validator('source_boards')
    @classmethod
    def valid_sources(cls,values):
        from .registry import destination
        return list(dict.fromkeys(destination('tieba',v) for v in values))
