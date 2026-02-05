from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .logger_config import get_logger

logger = get_logger()


@dataclass(frozen=True)
class FeishuWebhookConfig:
	webhook_url: str
	secret: str | None = None
	at_all: bool = False


def _truthy_env(name: str, default: bool = False) -> bool:
	v = os.getenv(name)
	if v is None:
		return default
	return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_feishu_budget_alert_config() -> FeishuWebhookConfig | None:
	"""
	Load Feishu/Lark custom-bot webhook config from env vars.

	Enabled when `FEISHU_BUDGET_ALERT_WEBHOOK_URL` is set.
	"""
	url = (os.getenv("FEISHU_BUDGET_ALERT_WEBHOOK_URL") or "").strip()
	if not url:
		return None

	secret = (os.getenv("FEISHU_BUDGET_ALERT_WEBHOOK_SECRET") or "").strip() or None
	at_all = _truthy_env("FEISHU_BUDGET_ALERT_AT_ALL", default=False)
	return FeishuWebhookConfig(webhook_url=url, secret=secret, at_all=at_all)


def _gen_sign(secret: str, timestamp: int) -> str:
	"""
	Feishu custom-bot signature (安全密钥):

	string_to_sign = f"{timestamp}\\n{secret}"
	sign = base64(HMAC_SHA256(key=string_to_sign, msg=""))
	"""
	string_to_sign = f"{timestamp}\n{secret}"
	hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
	return base64.b64encode(hmac_code).decode("utf-8")


def send_feishu_text(
	*,
	cfg: FeishuWebhookConfig,
	text: str,
	timeout_s: float = 10.0,
) -> dict[str, Any] | None:
	"""
	Send a text message to Feishu group via incoming webhook.

	Returns the parsed JSON response when possible.
	"""
	if not cfg.webhook_url:
		return None

	msg_text = text
	if cfg.at_all:
		msg_text = f'<at user_id="all">所有人</at>\n{msg_text}'

	payload: dict[str, Any] = {
		"msg_type": "text",
		"content": {"text": msg_text},
	}

	if cfg.secret:
		ts = int(time.time())
		payload["timestamp"] = ts
		payload["sign"] = _gen_sign(cfg.secret, ts)

	data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
	req = Request(cfg.webhook_url, data=data, headers={"Content-Type": "application/json"})

	try:
		with urlopen(req, timeout=timeout_s) as resp:
			raw = resp.read().decode("utf-8", errors="ignore")
	except (HTTPError, URLError) as e:
		logger.error(f"[FeishuWebhook] send failed: {e}")
		return None
	except Exception as e:
		logger.error(f"[FeishuWebhook] send failed: {e}")
		return None

	try:
		return json.loads(raw)
	except Exception:
		return {"raw": raw}

