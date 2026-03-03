from __future__ import annotations

import asyncio
import os
from functools import lru_cache
from typing import Any, TypeVar

import trans

T = TypeVar("T")


DEFAULT_SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_SILICONFLOW_EXTRACT_MODEL = "Pro/deepseek-ai/DeepSeek-V3.2"

DEFAULT_SANY_EXTRACT_MODEL = "deepseek-v3.2"

DEFAULT_OPENAI_EXTRACT_MODEL = "gpt-5.2"


def _normalize_base_url(url: str) -> str:
	return (url or "").rstrip("/")


def _get_sany_headers() -> dict[str, str] | None:
	# Optional: force gateway vendor routing (header X-ai-server)
	x_ai_server = os.getenv("SANY_X_AI_SERVER") or os.getenv("SANY_AI_SERVER")
	if not x_ai_server:
		return None
	return {"X-ai-server": x_ai_server}


def _to_lc_messages(messages: list[dict[str, str]]):
	# Lazy import: keep module import cheap and make failures explicit at runtime.
	from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

	out = []
	for m in messages or []:
		role = (m.get("role") or "").strip().lower()
		content = m.get("content") or ""
		if role == "system":
			out.append(SystemMessage(content=content))
		elif role == "assistant":
			out.append(AIMessage(content=content))
		else:
			# Default to user/human.
			out.append(HumanMessage(content=content))
	return out


@lru_cache(maxsize=8)
def _get_chat_model_cached(route: str, model_name: str, base_url: str, api_key: str, headers_key: str):
	from langchain_openai import ChatOpenAI

	default_headers = _get_sany_headers() if headers_key == "sany" else None
	# LangChain has renamed some init kwargs across versions. Try common variants for robustness.
	try:
		return ChatOpenAI(
			model=model_name,
			api_key=api_key,
			base_url=base_url,
			default_headers=default_headers,
			temperature=0,
		)
	except TypeError:
		try:
			return ChatOpenAI(
				model=model_name,
				api_key=api_key,
				base_url=base_url,
				temperature=0,
			)
		except TypeError:
			try:
				return ChatOpenAI(
					model=model_name,
					openai_api_key=api_key,
					openai_api_base=base_url,
					default_headers=default_headers,
					temperature=0,
				)
			except TypeError:
				return ChatOpenAI(
					model=model_name,
					openai_api_key=api_key,
					openai_api_base=base_url,
					temperature=0,
				)


def _get_chat_model(*, model: str | None = None):
	route = getattr(trans, "ROUTE", "official")

	if route == "sany":
		api_key = os.getenv("SANY_AI_GATEWAY_KEY") or os.getenv("SANY_AI_GATEWAY_API_KEY")
		if not api_key:
			raise RuntimeError("Missing SANY gateway api key. Set env var SANY_AI_GATEWAY_KEY.")
		base_url = _normalize_base_url(os.getenv("SANY_AI_GATEWAY_BASE_URL", "https://agent-api-test.sany.com.cn/ai-api"))
		model_name = (model or os.getenv("SANY_EXTRACT_MODEL") or DEFAULT_SANY_EXTRACT_MODEL).strip()
		return _get_chat_model_cached("sany", model_name, base_url, api_key, "sany")

	if route == "openai":
		api_key = os.getenv("OPENAI_API_KEY")
		if not api_key:
			raise RuntimeError("Missing OpenAI API key. Set env var OPENAI_API_KEY.")
		base_url = _normalize_base_url(os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
		model_name = (model or os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_EXTRACT_MODEL).strip()
		return _get_chat_model_cached("openai", model_name, base_url, api_key, "none")

	# default: official (SiliconFlow)
	api_key = os.getenv("SILICONFLOW_API_KEY") or os.getenv("SILICONFLOW_KEY")
	if not api_key:
		raise RuntimeError("Missing SiliconFlow API key: set env var SILICONFLOW_API_KEY")
	base_url = _normalize_base_url(os.getenv("SILICONFLOW_BASE_URL", DEFAULT_SILICONFLOW_BASE_URL))
	model_name = (model or os.getenv("SILICONFLOW_EXTRACT_MODEL") or DEFAULT_SILICONFLOW_EXTRACT_MODEL).strip()

	return _get_chat_model_cached("official", model_name, base_url, api_key, "none")


def invoke_structured(messages: list[dict[str, str]], schema: type[T], *, model: str | None = None) -> T:
	"""
	Invoke DeepSeek (via OpenAI-compatible endpoints) with LangChain structured output.

	Notes:
	- Only used for JSON-structured extraction/classification steps.
	- Markdown/plain-text transformations keep using src.extract_client.chat_completion.
	"""
	chat_model = _get_chat_model(model=model)
	runnable = chat_model.with_structured_output(schema)
	return runnable.invoke(_to_lc_messages(messages))


async def ainvoke_structured(messages: list[dict[str, str]], schema: type[T], *, model: str | None = None) -> T:
	"""
	Async variant of invoke_structured().

	Falls back to running invoke() in a thread when the underlying LangChain runnable
	does not provide ainvoke() (or when async invocation is not implemented).
	"""
	chat_model = _get_chat_model(model=model)
	runnable = chat_model.with_structured_output(schema)
	lc_messages = _to_lc_messages(messages)

	ainvoke = getattr(runnable, "ainvoke", None)
	if callable(ainvoke):
		try:
			return await ainvoke(lc_messages)
		except (NotImplementedError, AttributeError):
			# Fall back to sync invoke in a worker thread.
			pass

	return await asyncio.to_thread(runnable.invoke, lc_messages)


def _structured_output_debug_dict(obj: Any) -> dict[str, Any]:
	"""
	Best-effort conversion for logging/debugging without assuming schema type.
	"""
	if obj is None:
		return {}
	if hasattr(obj, "model_dump"):
		try:
			return obj.model_dump()
		except Exception:
			return {}
	if isinstance(obj, dict):
		return obj
	return {"value": obj}
