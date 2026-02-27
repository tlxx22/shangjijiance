from __future__ import annotations

import os
import socket
import threading
from datetime import datetime

from zoneinfo import ZoneInfo

from .feishu_webhook import FeishuWebhookConfig, send_feishu_text
from .logger_config import get_logger

logger = get_logger()


OFFICIAL_ENV_NAME = "environment"
OFFICIAL_ENV_VALUE = "sany_official"
OFFICIAL_FEISHU_WEBHOOK_URL = (
	"https://open.work.sany.com.cn/open-apis/bot/v2/hook/b65adfef-52d6-4c59-886c-f7c47acf975c"
)


def is_sany_official_env() -> bool:
	return os.getenv(OFFICIAL_ENV_NAME) == OFFICIAL_ENV_VALUE


def build_startup_text(*, server_meta: dict[str, str]) -> str:
	server_meta = server_meta or {}

	try:
		tz = ZoneInfo("Asia/Shanghai")
		ts = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
	except Exception:
		ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

	hostname = socket.gethostname()
	pid = str(server_meta.get("pid") or "")
	bind = str(server_meta.get("bind") or "")
	workers = str(server_meta.get("workers") or "")

	return (
		"crawler-agent 启动通知（sany_official）\n"
		f"- 时间(Asia/Shanghai): {ts}\n"
		f"- host: {hostname}\n"
		f"- pid: {pid}\n"
		f"- bind: {bind}\n"
		f"- workers: {workers}"
	)


def notify_startup_async(
	*,
	server_meta: dict[str, str],
	timeout_s: float = 3.0,
	sender=send_feishu_text,
	async_send: bool = True,
) -> None:
	if not is_sany_official_env():
		return

	cfg = FeishuWebhookConfig(webhook_url=OFFICIAL_FEISHU_WEBHOOK_URL, secret=None, at_all=False)
	text = build_startup_text(server_meta=server_meta or {})

	def _send() -> None:
		try:
			sender(cfg=cfg, text=text, timeout_s=timeout_s)
			logger.info("[FeishuWebhook] official startup notify sent")
		except Exception as e:
			logger.warning(f"[FeishuWebhook] official startup notify failed: {e}")

	if async_send:
		try:
			threading.Thread(target=_send, daemon=True, name="feishu-official-startup-notify").start()
		except Exception as e:
			# Never block startup; fall back to best-effort sync send.
			logger.warning(f"[FeishuWebhook] start notify thread failed, fallback to sync: {e}")
			_send()
	else:
		_send()
