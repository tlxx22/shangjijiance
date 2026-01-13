# Gunicorn 配置文件

bind = "0.0.0.0:80"
import os
workers = int(os.getenv("WORKERS", 5))
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 2000  # > timeout_seconds (1800)，留足余量
keepalive = 120
preload_app = False  # 不预加载，避免浏览器资源问题

# 日志
accesslog = "-"
errorlog = "-"
loglevel = "info"
