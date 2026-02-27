"""
CrawlSession - 管理单个爬取任务的生命周期
"""
import os
import asyncio
import time
import contextlib
from typing import AsyncIterator
from dataclasses import dataclass, field

from .sse_events import sse_event
from ..site_processor import process_site
from ..config_manager import SiteConfig
from ..logger_config import get_logger

logger = get_logger()


@dataclass
class CrawlSession:
    """
    封装单个爬取请求的状态和生命周期
    
    - queue: 事件队列，_run() 推送，event_generator 消费
    - cancel: 取消信号
    - _task: 后台爬虫任务
    """
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1000))
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    _task: asyncio.Task | None = None
    _cleanup_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _started: bool = False

    def start(
        self,
        site_config: SiteConfig,
        filter_prompt: str,
        request_id: str,
        max_pages: int = 3,
        headless: bool = True,
        date_start: str | None = None,
        date_end: str | None = None,
        product_category_table: str | None = None,
        engineering_machinery_only: bool = False,
    ):
        """
        启动后台爬虫任务
        
        必须在 SSE generator 内调用，确保只有流开始消费时才启动
        """
        if self._started:
            return
        self._started = True
        
        self._task = asyncio.create_task(
            self._run(
                site_config,
                filter_prompt,
                request_id,
                max_pages,
                headless,
                date_start,
                date_end,
                product_category_table,
                engineering_machinery_only,
            )
        )

    async def _run(
        self,
        site_config: SiteConfig,
        filter_prompt: str,
        request_id: str,
        max_pages: int,
        headless: bool,
        date_start: str | None,
        date_end: str | None,
        product_category_table: str | None,
        engineering_machinery_only: bool,
    ):
        """
        后台爬虫任务，推送事件到队列
        """
        # 发送 start 事件
        await self.queue.put({
            "type": "start",
            "site_name": site_config.name,
            "url": str(site_config.url),
        })
        
        try:
            # 创建回调函数：每保存一条数据就推送到 SSE queue
            def on_item_saved(json_data: dict):
                """将保存的 item 数据推送到 SSE 队列"""
                try:
                    # 使用 put_nowait 避免阻塞（队列满时会丢弃）
                    self.queue.put_nowait({
                        "type": "item",
                        "data": json_data,
                    })
                except asyncio.QueueFull:
                    logger.warning("[CrawlSession] SSE 队列已满，item 被丢弃")
            
            # 调用现有的 process_site 函数
            result = await process_site(
                site_config=site_config,
                filter_prompt=filter_prompt,
                headless=headless,
                max_pages=max_pages,
                max_retries=1,  # SSE 模式不重试整站
                on_item_saved=on_item_saved,
                date_start=date_start,
                date_end=date_end,
                product_category_table=product_category_table,
                engineering_machinery_only=engineering_machinery_only,
            )
            
            # 根据结果发送 done 或 error
            if result.get("status") == "success":
                await self.queue.put({
                    "type": "done",
                    "items_found": result.get("items_found", 0),
                    "pages_processed": result.get("pages_processed", 0),
                })
            elif result.get("status") == "risk_control":
                await self.queue.put({
                    "type": "error",
                    "message": "触发风控/反爬机制",
                    "items_found": result.get("items_found", 0),
                })
            else:
                await self.queue.put({
                    "type": "error",
                    "message": result.get("error", "未知错误"),
                })
                
        except asyncio.CancelledError:
            # 被取消时不发送任何事件
            raise
        except Exception as e:
            logger.error(f"[CrawlSession] 爬取失败: {e}")
            await self.queue.put({
                "type": "error",
                "message": str(e),
            })

    async def cleanup(self):
        """
        幂等清理，带超时上限防止卡住 worker
        
        cleanup() 超时后 os._exit(1) 让 worker 自杀，
        确保不会留下僵尸任务和 Chrome 进程
        """
        async with self._cleanup_lock:
            self.cancel.set()
            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await asyncio.wait_for(self._task, timeout=10)
                except asyncio.CancelledError:
                    pass
                except asyncio.TimeoutError:
                    logger.error("cleanup 超时，强制退出 worker")
                    os._exit(1)


async def event_generator(
    session: CrawlSession,
    request_id: str,
    timeout_seconds: int,
    http_request=None,  # 用于断线检测
) -> AsyncIterator[str]:
    """
    SSE 事件生成器
    
    - 轮询 session.queue
    - 发送心跳（30秒无输出）
    - 检测超时
    - 每 2s 检测客户端断线
    - 最终调用 cleanup
    
    断线机制说明：uvicorn/starlette (ASGI spec>=2.4) 主要通过 send() 失败
    (OSError -> ClientDisconnect) 检测断线，此处额外用 is_disconnected() 检测
    以便更快（≈2s）感知并停止生成。
    """
    start = time.monotonic()
    deadline = start + timeout_seconds
    last_output = start
    
    try:
        while True:
            # 检查请求超时
            now = time.monotonic()
            if now >= deadline:
                yield sse_event({"type": "error", "message": "timeout"}, request_id)
                return
            
            # 轮询队列
            try:
                event = await asyncio.wait_for(session.queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                # 每 2s 检查一次断线
                if http_request and await http_request.is_disconnected():
                    logger.warning(f"[{request_id}] 客户端断线，停止生成")
                    return
                now = time.monotonic()  # 重新取时间
                if now - last_output >= 30:
                    yield sse_event({"type": "heartbeat"}, request_id)
                    last_output = now
                continue
            
            # 发送事件
            yield sse_event(event, request_id)
            last_output = time.monotonic()
            
            # done 或 error 是终止信号
            if event.get("type") in ("done", "error"):
                return
                
    finally:
        await session.cleanup()
