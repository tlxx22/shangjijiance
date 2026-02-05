"""
Pydantic 请求/响应模型
"""
from datetime import date
from pydantic import BaseModel, HttpUrl, Field, constr, model_validator


class SiteInfo(BaseModel):
    """网站信息"""
    name: constr(min_length=1)
    url: HttpUrl
    login_required: bool = False
    username: str | None = None
    password: str | None = None

    @model_validator(mode='after')
    def check_credentials(self):
        if self.login_required:
            if not self.username or not self.password:
                raise ValueError("login_required=True 时必须提供 username 和 password")
        return self


class CrawlRequest(BaseModel):
    """爬取请求"""
    site: SiteInfo
    date_start: date
    date_end: date
    category: constr(min_length=1)
    timeout_seconds: int = 1800  # 30分钟
    max_pages: int = 3
    headless: bool = True

    @model_validator(mode='after')
    def check_dates(self):
        if self.date_start > self.date_end:
            raise ValueError("date_start > date_end")
        return self


class EmbeddingRequest(BaseModel):
    """向量化请求"""
    text: constr(min_length=1) = Field(description="待向量化的文本（通常为公告名称）")
    model: str | None = Field(default=None, description="可选：覆盖默认 embedding 模型名")
    dimension: int = Field(default=2048, ge=1, description="可选：embedding 向量维度（dimension），默认 2048")


class EmbeddingResponse(BaseModel):
    """向量化响应"""
    model: str = Field(description="实际使用的模型名")
    embedding: list[float] = Field(description="向量值")


class MarkdownRequest(BaseModel):
    """公告原文转 Markdown 请求"""
    announcementContent: constr(min_length=1) = Field(description="已清洗的公告原文内容（通常为 HTML 字符串）")


class MarkdownResponse(BaseModel):
    """公告原文转 Markdown 响应"""
    markdown: str = Field(description="结构化 Markdown 文本")


class NormalizeItemRequest(BaseModel):
    """任意来源 JSON 映射到统一模板的请求"""
    sourceJson: constr(min_length=1) = Field(description="其它来源的数据 JSON（由后端拼接成字符串传入）")


class NormalizeItemResponse(BaseModel):
    """任意来源 JSON 映射到统一模板的响应"""
    data: dict = Field(description="统一 item 模板 JSON")
