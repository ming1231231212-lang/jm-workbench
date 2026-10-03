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
    source_title: str = Field(default='',max_length=200)
    source_excerpt: str = Field(default='',max_length=6000)

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
