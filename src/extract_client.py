from __future__ import annotations

import os
from typing import Any

from openai import OpenAI

import trans


DEFAULT_SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_SILICONFLOW_EXTRACT_MODEL = "Pro/deepseek-ai/DeepSeek-V3.2"

DEFAULT_SANY_EXTRACT_MODEL = "deepseek-v3.2"
DEFAULT_SANY_MAX_TOKENS = 8192

DEFAULT_OPENAI_EXTRACT_MODEL = "deepseek-v3-2-251201"


def _normalize_base_url(url: str) -> str:
	return (url or "").rstrip("/")


def _get_sany_headers() -> dict[str, str] | None:
	# Optional: force gateway vendor routing (header X-ai-server)
	x_ai_server = os.getenv("SANY_X_AI_SERVER") or os.getenv("SANY_AI_SERVER")
	if not x_ai_server:
		return None
	return {"X-ai-server": x_ai_server}


def chat_completion(messages: list[dict[str, str]], *, model: str | None = None) -> str:
	"""
	Call an OpenAI-compatible Chat Completions endpoint and return the assistant content.

	Routing:
	- trans.ROUTE == "official": SiliconFlow (OpenAI-compatible /v1/chat/completions)
	- trans.ROUTE == "sany": SANY gateway (OpenAI-compatible /ai-api/chat/completions)
	- trans.ROUTE == "openai": OpenAI-compatible endpoint via env OPENAI_BASE_URL/OPENAI_API_KEY
	"""
	route = getattr(trans, "ROUTE", "official")

	if route == "sany":
		api_key = os.getenv("SANY_AI_GATEWAY_KEY") or os.getenv("SANY_AI_GATEWAY_API_KEY")
		if not api_key:
			raise RuntimeError("Missing SANY gateway api key. Set env var SANY_AI_GATEWAY_KEY.")
		base_url = _normalize_base_url(os.getenv("SANY_AI_GATEWAY_BASE_URL", "https://agent-api-test.sany.com.cn/ai-api"))
		model_name = (model or os.getenv("SANY_EXTRACT_MODEL") or DEFAULT_SANY_EXTRACT_MODEL).strip()

		client = OpenAI(api_key=api_key, base_url=base_url, default_headers=_get_sany_headers())
		resp: Any = client.chat.completions.create(
			model=model_name,
			messages=messages,
			max_tokens=DEFAULT_SANY_MAX_TOKENS,
		)
		return (resp.choices[0].message.content or "").strip()

	if route == "openai":
		api_key = os.getenv("OPENAI_API_KEY")
		if not api_key:
			raise RuntimeError("Missing OpenAI API key. Set env var OPENAI_API_KEY.")
		base_url = _normalize_base_url(os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
		model_name = (model or os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_EXTRACT_MODEL).strip()

		client = OpenAI(api_key=api_key, base_url=base_url)
		resp: Any = client.chat.completions.create(model=model_name, messages=messages)
		return (resp.choices[0].message.content or "").strip()

	# default: official
	api_key = os.getenv("SILICONFLOW_API_KEY") or os.getenv("SILICONFLOW_KEY")
	if not api_key:
		raise RuntimeError("Missing SiliconFlow API key: set env var SILICONFLOW_API_KEY")
	base_url = _normalize_base_url(os.getenv("SILICONFLOW_BASE_URL", DEFAULT_SILICONFLOW_BASE_URL))
	model_name = (model or os.getenv("SILICONFLOW_EXTRACT_MODEL") or DEFAULT_SILICONFLOW_EXTRACT_MODEL).strip()

	client = OpenAI(api_key=api_key, base_url=base_url)
	resp: Any = client.chat.completions.create(model=model_name, messages=messages)
	return (resp.choices[0].message.content or "").strip()
