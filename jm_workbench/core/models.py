import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .platforms import PLATFORMS


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class AccountInput(Strict):
    name: str = Field(min_length=1, max_length=40)
    platform: str
    profile_dir: str = Field(default='', max_length=500)
    enabled: bool = True

    @field_validator('platform')
    @classmethod
    def platform_known(cls, v):
        if v not in PLATFORMS:
            raise ValueError('平台尚未接入')
        return v


class TaskInput(Strict):
    name: str = Field(min_length=1, max_length=60)
    platform: str
    kind: Literal['crawler', 'adult_comments', 'peiwang_comments']
    keywords: list[str] = Field(min_length=1, max_length=10)
    max_items: int = Field(default=10, ge=1, le=20)
    collect_comments: bool = False
    comments_per_item: int = Field(default=10, ge=1, le=20)
    max_publish: int = Field(default=1, ge=1, le=5)
    templates: list[str] = Field(default_factory=list, max_length=10)
    adult_target: Literal['inventory', 'merchant'] = 'inventory'
    comment_mode: Literal['templates', 'core_variants'] = 'templates'
    comment_core: str = Field(default='', max_length=80)
    start_hour: int = Field(default=20, ge=8, le=22)
    end_hour: int = Field(default=23, ge=9, le=23)
    enabled: bool = True

    @model_validator(mode='after')
    def validate_task(self):
        if self.platform not in PLATFORMS:
            raise ValueError('平台尚未接入')
        if self.start_hour >= self.end_hour:
            raise ValueError('结束时间必须晚于开始时间')
        if self.kind != 'crawler':
            if not PLATFORMS[self.platform]['comment']:
                raise ValueError('此平台当前仅支持爬虫，评论接口预留')
            if self.start_hour < 20:
                raise ValueError('评论时段限定20:00至23:00，可进一步缩短')
            from ..policies.rules import validate_template
            if self.comment_mode == 'core_variants':
                if self.kind != 'adult_comments':
                    raise ValueError('核心句变体当前仅用于成人用品收货业务')
                from ..policies.comments import variants
                variants(self.comment_core)
            else:
                if not self.templates:
                    raise ValueError('请配置至少一条评论模板')
                for text in self.templates:
                    validate_template(self.kind, text)
        if any(not v.strip() or len(v) > 40 or re.search(r'[\r\n\x00,，]', v) for v in self.keywords):
            raise ValueError('每行一个关键词，长度1至40字，不含逗号')
        self.keywords = list(dict.fromkeys(v.strip() for v in self.keywords))
        if self.platform == 'ks' and any('.' in v for v in self.keywords):
            raise ValueError('快手关键词不能包含英文句点，请使用自然语言关键词')
        return self


class BindingInput(Strict):
    task_id: str
    account_id: str
    enabled: bool = True


class SettingsInput(Strict):
    chrome_path: str = Field(max_length=500)
    crawler_root: str = Field(max_length=500)
    crawler_python: str = Field(max_length=500)


class LaunchInput(Strict):
    task_id: str | None = None


class ClearRiskInput(Strict):
    note: str = Field(min_length=12, max_length=300)
