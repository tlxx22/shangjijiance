"""
SSE HTTP API 服务主入口

使用方式：
- 开发模式：uvicorn app:app --reload
- 生产模式：gunicorn -c gunicorn.conf.py app:app
"""
import asyncio
import json
import os
import sys
import uuid

import requests
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse, Response, StreamingResponse

from src.third_rpc import (
    bidcenter_post,
    browser_billing as browser_billing_logic,
    jy_fetch as jy_fetch_logic,
)

# Windows asyncio 兼容性修复：browser-use 需要 ProactorEventLoop 来启动浏览器进程
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# 加载 .env 文件（BROWSER_USE_API_KEY 等）
from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

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
from src.address_normalizer import extract_admin_divisions_from_details
from src.custom_tools import compute_data_id, _parse_address_parts_from_detail
from src.announcement_type_repair import AnnouncementTypeRepairError
from src.browser_use_budget import get_budget

logger = get_logger()


def _current_worker_label() -> str:
    worker_index = os.getenv("UVICORN_WORKER_INDEX") or "unknown"
    worker_port = os.getenv("UVICORN_WORKER_PORT") or "unknown"
    return f"worker#{worker_index}(pid={os.getpid()}, port={worker_port})"


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
    request_id = uuid.uuid4().hex[:8]
    worker_label = _current_worker_label()
    client_host = http_request.client.host if http_request.client else "-"
    logger.info(f"[{request_id}] /crawl routed to {worker_label}, client={client_host}, site={request.site.name}")

    try:
        template = load_prompt_template(request.category)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Daily budget guard (cross-worker): stop starting new crawl tasks once threshold reached.
    if get_budget().is_stopped():
        st = get_budget().status()
        get_budget().maybe_send_alert(st)
        raise HTTPException(429, f"Daily browser-use budget exceeded: spent=${st.spent_usd:.4f}, limit=${st.limit_usd:.2f}")
     
    # 2. 非阻塞拿锁
    if crawl_lock.locked():
        logger.warning(
            f"[{request_id}] /crawl rejected by {worker_label}: Worker busy, client={client_host}, site={request.site.name}"
        )
        raise HTTPException(429, "Worker busy")
    await crawl_lock.acquire()
    logger.info(f"[{request_id}] /crawl accepted by {worker_label}, client={client_host}, site={request.site.name}")
    
    # 3. 只准备 session，不启动爬虫
    try:
        
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
                    product_category_table=request.productCategoryTable,
                    engineering_machinery_only=request.engineering_machinery_only,
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

@app.get("/browser_billing")
async def browser_billing():
    """浏览器计费"""
    return browser_billing_logic()

async def _form_dict_from_request(request: Request) -> dict:
    ct = (request.headers.get("content-type") or "").lower()
    if "application/json" in ct:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        out: dict = {}
        for k, v in payload.items():
            if isinstance(v, (dict, list)):
                continue
            if v is None:
                out[str(k)] = ""
            elif isinstance(v, bool):
                out[str(k)] = "true" if v else "false"
            else:
                out[str(k)] = str(v)
        return out

    form = await request.form()
    out = {}
    for k, v in form.multi_items():
        if isinstance(v, str):
            out[k] = v
    return out


def _pop_upstream_url(form_data: dict) -> tuple[str, dict]:
    """
    从表单中取出上游地址（参数名 upstream_url 或 url），其余字段原样转发给 bidcenter。
    """
    data = dict(form_data)
    raw = data.pop("upstream_url", None) or data.pop("url", None)
    if raw is None or not str(raw).strip():
        raise ValueError("upstream_url is required (or use alias: url)")
    raw = str(raw).strip()
    p = urlparse(raw)
    if p.scheme not in ("http", "https"):
        raise ValueError("upstream_url must be http or https")
    if not p.netloc:
        raise ValueError("upstream_url is not a valid URL")
    return raw, data


async def _bidcenter_proxy(request: Request, route_label: str):
    try:
        form_data = await _form_dict_from_request(request)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"{route_label} parse body failed: {e}")
        raise HTTPException(400, "Invalid request body")

    try:
        upstream_url, payload = _pop_upstream_url(form_data)
    except ValueError as e:
        raise HTTPException(400, str(e))

    try:
        upstream = await asyncio.to_thread(bidcenter_post, upstream_url, payload)
    except requests.exceptions.RequestException as e:
        logger.error(f"{route_label} upstream error: {e}")
        raise HTTPException(502, f"Upstream request failed: {e}")

    media = upstream.headers.get("Content-Type") or "application/json; charset=utf-8"
    return Response(content=upstream.content, status_code=upstream.status_code, media_type=media)


@app.post("/bidcenter/search")
async def bidcenter_search_proxy(request: Request):
    """
    代理招中标搜索：POST，除 **upstream_url**（或 **url**）外，其余参数原样转发为上游 form-urlencoded。
    upstream_url 为完整 HTTPS 接口地址，例如 https://api.bidcenter.com.cn/custom/250549/Search.ashx
    """
    return await _bidcenter_proxy(request, "/bidcenter/search")


@app.post("/bidcenter/detail")
async def bidcenter_detail_proxy(request: Request):
    """
    代理招中标详情：POST，除 **upstream_url**（或 **url**）外，其余参数原样转发（详情接口需含 id）。
    upstream_url 示例：https://api.bidcenter.com.cn/custom/250549/Detail.ashx
    """
    return await _bidcenter_proxy(request, "/bidcenter/detail")


@app.get("/jy_fetch")
async def jy_fetch(
    timestamp:  Optional[str] = Query(None, description="时间戳")
    ,signature: Optional[str] = Query(None, description="签名")
    ,next_page: Optional[str] = Query(None, description="下一页token")):
    """ 剑鱼数据获取 返回json数据"""
    return jy_fetch_logic(timestamp=timestamp,signature=signature,next_page=next_page)


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
        model_name, vector = await asyncio.to_thread(
            get_text_embedding,
            req.text,
            model=req.model,
            dimensions=req.dimension,
        )
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
    将任意来源（第三方 API / Excel 等）的文本（推荐：中文标签 Markdown）映射为统一 item 模板（由 DeepSeek 生成）。
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
        item = await normalize_source_json_to_item(
            req.sourceJson,
            product_category_table=req.productCategoryTable,
        )

        # 地址字段：不再用正则拆分；改为一次调用 LLM 从三组 AddressDetail 提取 12 个字段。
        # 规则：
        # - AddressDetail 为空：country="中国"，省市区为空字符串
        # - 整体最多重试 3 次；超过上限逐字段回退原值；只影响 12 个字段，不包含 AddressDetail
        try:
            addr = await extract_admin_divisions_from_details(
                buyer_address_detail=item.get("buyerAddressDetail", ""),
                project_address_detail=item.get("projectAddressDetail", ""),
                delivery_address_detail=item.get("deliveryAddressDetail", ""),
                original_item=item,
                max_retries=3,
            )
            item.update(addr)
        except Exception as norm_err:
            logger.warning(f"/normalize_item 地址字段 LLM 提取失败（已跳过）: {norm_err}")

        item["dataId"] = compute_data_id(item)
        return {"data": item}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except AnnouncementTypeRepairError as e:
        raise HTTPException(
            422,
            {"message": str(e), "rawType": e.raw_type, "maxRetries": e.max_retries},
        )
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except Exception as e:
        logger.error(f"/normalize_item failed: {e}")
        raise HTTPException(502, f"Upstream normalize error: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
