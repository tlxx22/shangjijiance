"""
SSE HTTP API 服务主入口

使用方式：
- 开发模式：uvicorn app:app --reload
- 生产模式：gunicorn -c gunicorn.conf.py app:app
"""
import asyncio
import sys
import uuid
from pathlib import Path

# Windows asyncio 兼容性修复：browser-use 需要 ProactorEventLoop 来启动浏览器进程
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# 加载 .env 文件（BROWSER_USE_API_KEY 等）
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.api.models import CrawlRequest
from src.api.prompt_manager import load_prompt_template, render_prompt
from src.api.crawl_session import CrawlSession, event_generator
from src.config_manager import SiteConfig
from src.logger_config import get_logger

logger = get_logger()

app = FastAPI(
    title="商机监测 API",
    description="SSE 流式爬取招标信息",
    version="1.0.0",
)

# 自定义验证错误处理：返回 400 而不是 422
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """将 Pydantic 验证错误从 422 改为 400"""
    return JSONResponse(
        status_code=400,
        content={"detail": exc.errors()}
    )

# 进程内互斥锁：每个 worker 进程独立
crawl_lock = asyncio.Lock()


class CrawlStreamingResponse(StreamingResponse):
    """
    带锁释放兜底的 StreamingResponse
    
    解决问题：如果客户端在响应头发送阶段断线，generator 可能不会执行，
    导致锁永远不释放。此类在 __call__ 的 finally 中兜底释放锁。
    
    断线机制说明：uvicorn/starlette (ASGI spec>=2.4) 主要通过 send() 失败
    (OSError -> ClientDisconnect) 检测断线，而非 CancelledError。
    """
    def __init__(self, content, lock: asyncio.Lock, **kwargs):
        super().__init__(content, **kwargs)
        self._lock = lock
    
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # 唯一锁释放点：响应生命周期结束时释放
            self._lock.release()


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok"}


@app.post("/crawl")
async def crawl(request: CrawlRequest, http_request: Request):
    """
    爬取指定网站的招标信息
    
    返回 SSE 流，事件类型：
    - start: 开始爬取
    - item: 每保存一条详情（逐条输出）
    - heartbeat: 每30秒无输出发出心跳
    - done: 爬取完成
    - error: 出错
    """
    # 1. 先检查 category（无效请求不占 worker）
    try:
        template = load_prompt_template(request.category)
    except ValueError as e:
        raise HTTPException(400, str(e))
    
    # 2. 非阻塞拿锁
    if crawl_lock.locked():
        raise HTTPException(429, "Worker busy")
    await crawl_lock.acquire()
    
    # 3. 只准备 session，不启动爬虫
    try:
        request_id = uuid.uuid4().hex[:8]
        
        # 构建 SiteConfig
        site_config = SiteConfig(
            name=request.site.name,
            url=str(request.site.url),
            login_required=request.site.login_required,
            username=request.site.username,
            password=request.site.password,
        )
        
        # 渲染 prompt（传入今天日期用于兜底规则）
        from datetime import date
        filter_prompt = render_prompt(
            template,
            category=request.category,
            site_name=request.site.name,
            date_start=str(request.date_start),
            date_end=str(request.date_end),
            today=str(date.today()),
        )
        
        # 创建 session（还不启动）
        session = CrawlSession()
        
        # session.start() 放到 wrapped() 里，确保爬虫只在流开始时启动
        async def wrapped():
            session.start(
                site_config=site_config,
                filter_prompt=filter_prompt,
                request_id=request_id,
                max_pages=request.max_pages,
                headless=request.headless,
                date_start=str(request.date_start),
                date_end=str(request.date_end),
            )
            async for chunk in event_generator(
                session=session,
                request_id=request_id,
                timeout_seconds=request.timeout_seconds,
                http_request=http_request,  # 传入 http_request 用于断线检测
            ):
                yield chunk
            # 注意：锁释放由 CrawlStreamingResponse.__call__ 的 finally 处理
        
        return CrawlStreamingResponse(
            wrapped(),
            lock=crawl_lock,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception:
        crawl_lock.release()  # 初始化失败，释放锁
        raise


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
