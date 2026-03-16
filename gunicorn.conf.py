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

# 三一正式环境启动通知已迁移到 deploy/entrypoint.sh，
# 避免 legacy_gunicorn 模式与统一启动入口重复发送。
