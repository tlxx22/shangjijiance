"""
Pydantic 请求/响应模型
"""
from datetime import date
from pydantic import BaseModel, HttpUrl, constr, model_validator


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
