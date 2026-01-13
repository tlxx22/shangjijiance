"""
日志配置模块

使用 Loguru 实现文件日志，支持:
- 固定文件名 (logs/app.log)
- 按大小自动轮转 (默认100MB)
- 自动清理旧日志 (默认保留5个归档)
- JSON 格式输出 (适合 SLS 采集)
- 异步写入 (多进程安全)
- 自动注入 request_id (通过 contextvars)
"""

import sys
import contextvars
from pathlib import Path
from loguru import logger as _raw_logger


# ===== ContextVars: 用于跨调用栈传递 request_id =====
_request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def set_request_id(request_id: str) -> contextvars.Token:
    """
    设置当前请求的 request_id
    
    Returns:
        Token 用于后续 reset
    """
    return _request_id_ctx.set(request_id)


def reset_request_id(token: contextvars.Token):
    """重置 request_id 到之前的值"""
    _request_id_ctx.reset(token)


def get_request_id() -> str | None:
    """获取当前请求的 request_id"""
    return _request_id_ctx.get()


# ===== Patcher: 自动注入 request_id 到每条日志 =====
def _request_id_patcher(record):
    """Loguru patcher: 自动注入 request_id 到 extra"""
    record["extra"]["request_id"] = get_request_id() or "-"


# ===== 全局配置好的 logger =====
# 使用 patch 添加 patcher
logger = _raw_logger.patch(_request_id_patcher)


# ===== 初始化标记 =====
_initialized = False


def init_logger(
    log_dir: str = "logs",
    max_size: str = "100 MB",
    retention: int = 5,
    level: str = "INFO",
) -> None:
    """
    初始化 Loguru 日志系统
    
    Args:
        log_dir: 日志目录路径
        max_size: 单个日志文件最大大小 (如 "100 MB", "1 GB")
        retention: 保留的归档文件数量
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    global _initialized
    
    # 防止重复初始化（多 worker 场景）
    if _initialized:
        return
    _initialized = True
    
    # 确保日志目录存在
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    
    # 移除默认 handler（避免重复日志）
    _raw_logger.remove()
    
    # 配置控制台日志（开发时可见）
    _raw_logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
    )
    
    # 配置文件日志（JSON 格式，适合 SLS 采集）
    _raw_logger.add(
        f"{log_dir}/app.log",
        rotation=max_size,       # 文件大小超过限制时轮转
        retention=retention,     # 保留的归档文件数量
        serialize=True,          # JSON 格式输出
        enqueue=True,            # 异步写入，多进程安全
        level=level,             # 日志级别
        encoding="utf-8",        # 文件编码
        backtrace=True,          # 启用完整堆栈跟踪
        diagnose=True,           # 启用变量诊断
    )
    
    logger.bind(
        log_dir=log_dir,
        max_size=max_size,
        retention=retention,
        level=level,
    ).info("Logger initialized")


def get_logger():
    """
    获取配置好的 logger 实例
    
    所有模块应该通过此函数获取 logger，确保统一配置
    """
    return logger


# ===== 兼容旧接口 =====
def setup_logger(name: str = "shangjijiance", log_dir: str = "output"):
    """
    兼容旧接口，实际调用 init_logger()
    
    """
    init_logger()
    return logger


def setup_worker_logger(worker_id: int, log_dir, name: str = "shangjijiance"):
    """
    兼容旧接口，用 extra.worker_id 区分
    
    保留此函数是为了兼容 concurrent_processor.py 的 import
    """
    init_logger()
    return logger.bind(worker_id=worker_id)
