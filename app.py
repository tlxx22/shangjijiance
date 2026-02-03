"""
SSE HTTP API 服务主入口

使用方式：
- 开发模式：uvicorn app:app --reload
- 生产模式：gunicorn -c gunicorn.conf.py app:app
"""
import asyncio
import json
import sys
import uuid
from pathlib import Path

# Windows asyncio 兼容性修复：browser-use 需要 ProactorEventLoop 来启动浏览器进程
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# 加载 .env 文件（BROWSER_USE_API_KEY 等）
from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.api.models import (
    CrawlRequest,
    EmbeddingRequest,
    EmbeddingResponse,
    MarkdownRequest,
    MarkdownResponse,
    NormalizeItemRequest,
    NormalizeItemResponse,
)
from src.api.prompt_manager import load_prompt_template, render_prompt
from src.api.crawl_session import CrawlSession, event_generator
from src.config_manager import SiteConfig
from src.logger_config import get_logger, init_logger, set_request_id, reset_request_id
from src.embedding_client import get_text_embedding
from src.llm_transform import convert_announcement_content_to_markdown, normalize_source_json_to_item
from src.custom_tools import compute_data_id, _parse_address_parts_from_detail

logger = get_logger()


# ===== FastAPI Lifespan =====
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化日志"""
    init_logger()
    logger.info("商机监测 API 服务启动")
    yield
    logger.info("商机监测 API 服务关闭")


app = FastAPI(
    title="商机监测 API",
    description="SSE 流式爬取招标信息",
    version="1.0.0",
    lifespan=lifespan,
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
            # 设置 request_id 到 contextvars，自动注入到所有日志
            token = set_request_id(request_id)
            try:
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
            finally:
                # 重置 request_id，防止串号
                reset_request_id(token)
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


@app.post("/embedding", response_model=EmbeddingResponse)
async def embedding(http_request: Request):
    """
    将输入文本（通常为公告名称）向量化并返回 embedding。
    """
    try:
        # FastAPI/Starlette 在遇到某些 curl/代理组合时，可能在参数绑定阶段就报
        # "There was an error parsing the body"（用户看不到具体原因）。
        # 这里改为手动解析，支持：
        # - application/json: {"text": "...", "model": "..."}
        # - text/plain: 直接把 body 当 text
        raw = await http_request.body()
        text_fallback = raw.decode("utf-8", errors="ignore").strip()

        payload: dict
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                payload = {"text": text_fallback}
        except Exception:
            payload = {"text": text_fallback}

        req = EmbeddingRequest.model_validate(payload)
        model_name, vector = await asyncio.to_thread(get_text_embedding, req.text, model=req.model)
        return {"model": model_name, "embedding": vector}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        # Server misconfiguration (missing key/base_url, etc.)
        raise HTTPException(500, str(e))
    except Exception as e:
        logger.error(f"/embedding failed: {e}")
        raise HTTPException(502, f"Upstream embedding error: {e}")


@app.post("/content_to_md", response_model=MarkdownResponse)
async def content_to_md(http_request: Request):
    """
    将已清洗的 announcementContent 转为结构清晰的 Markdown 文本（由 DeepSeek 生成）。
    """
    try:
        raw = await http_request.body()
        text_fallback = raw.decode("utf-8", errors="ignore").strip()

        payload: dict
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                payload = {"announcementContent": text_fallback}
        except Exception:
            payload = {"announcementContent": text_fallback}

        req = MarkdownRequest.model_validate(payload)
        md = await convert_announcement_content_to_markdown(req.announcementContent)
        return {"markdown": md}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except Exception as e:
        logger.error(f"/content_to_md failed: {e}")
        raise HTTPException(502, f"Upstream markdown error: {e}")


@app.post("/normalize_item", response_model=NormalizeItemResponse)
async def normalize_item(http_request: Request):
    """
    将任意来源（第三方 API / Excel 等）的 JSON 字符串映射为统一 item 模板（由 DeepSeek 生成）。
    """
    try:
        raw = await http_request.body()
        text_fallback = raw.decode("utf-8", errors="ignore").strip()

        payload: dict
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                payload = {"sourceJson": text_fallback}
        except Exception:
            payload = {"sourceJson": text_fallback}

        req = NormalizeItemRequest.model_validate(payload)
        item = await normalize_source_json_to_item(req.sourceJson)

        # 地址字段：与 save_detail 保持一致，统一从 AddressDetail 解析（或兜底为中国）。
        for prefix in ("buyer", "project", "delivery"):
            detail_key = f"{prefix}AddressDetail"
            country_key = f"{prefix}Country"
            province_key = f"{prefix}Province"
            city_key = f"{prefix}City"
            district_key = f"{prefix}District"

            detail = (item.get(detail_key) or "").strip()
            if not detail:
                item[country_key] = "中国"
                item[province_key] = ""
                item[city_key] = ""
                item[district_key] = ""
            else:
                parts = _parse_address_parts_from_detail(detail)
                item[country_key] = parts.country or "中国"
                item[province_key] = parts.province
                item[city_key] = parts.city
                item[district_key] = parts.district

        item["dataId"] = compute_data_id(item)
        return {"data": item}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except Exception as e:
        logger.error(f"/normalize_item failed: {e}")
        raise HTTPException(502, f"Upstream normalize error: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
