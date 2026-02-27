# Gunicorn 配置文件

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

bind = "0.0.0.0:80"
workers = int(os.getenv("WORKERS", 5))
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 2000  # > timeout_seconds (1800)，留足余量
keepalive = 120
preload_app = False  # 不预加载，避免浏览器资源问题

# 日志
accesslog = "-"
errorlog = "-"
loglevel = "info"


def when_ready(server):
    """
    Gunicorn master hook (runs once per master start).
    Send Feishu startup notification ONLY in sany_official environment.
    """
    try:
        cfg = getattr(server, "cfg", None)
        server_meta = {
            "pid": str(getattr(server, "pid", "") or os.getpid()),
            "workers": str(getattr(cfg, "workers", "") or ""),
            "bind": str(getattr(cfg, "bind", "") or ""),
        }
        from src.official_startup_notify import notify_startup_async

        notify_startup_async(server_meta=server_meta, timeout_s=3.0)
    except Exception:
        # Must never fail the service startup.
        pass
