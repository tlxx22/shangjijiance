from __future__ import annotations

import asyncio
import json
import os
import re
from functools import lru_cache
from urllib.parse import urlparse
from typing import Any, TypeVar

import trans

T = TypeVar("T")


DEFAULT_SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_SILICONFLOW_EXTRACT_MODEL = "Pro/deepseek-ai/DeepSeek-V3.2"

DEFAULT_SANY_EXTRACT_MODEL = "deepseek-v4-flash"
DEFAULT_SANY_MAX_TOKENS = 8192

DEFAULT_OPENAI_EXTRACT_MODEL = "deepseek-v4-flash"
DEFAULT_STRUCTURED_MAX_TOKENS = 8192
DEFAULT_REQUEST_TIMEOUT_SECONDS = 180.0

_JSON_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _normalize_base_url(url: str) -> str:
	return (url or "").rstrip("/")


def _get_sany_headers() -> dict[str, str] | None:
	# Optional: force gateway vendor routing (header X-ai-server)
	x_ai_server = os.getenv("SANY_X_AI_SERVER") or os.getenv("SANY_AI_SERVER")
	if not x_ai_server:
		return None
	return {"X-ai-server": x_ai_server}


def _get_env_float(name: str, default: float) -> float:
	value = (os.getenv(name) or "").strip()
	if not value:
		return default
	try:
		return float(value)
	except ValueError:
		return default


def _get_env_int(name: str, default: int) -> int:
	value = (os.getenv(name) or "").strip()
	if not value:
		return default
	try:
		return int(value)
	except ValueError:
		return default


def _is_deepseek_official_base_url(base_url: str) -> bool:
	host = (urlparse(base_url).hostname or "").strip().lower()
	return host in {"api.deepseek.com", "api.deepseek.cn"} or host.endswith(".deepseek.com") or host.endswith(".deepseek.cn")


def _get_deepseek_structured_thinking_mode(base_url: str) -> str | None:
	if not _is_deepseek_official_base_url(base_url):
		return None

	value = (os.getenv("DEEPSEEK_STRUCTURED_THINKING") or os.getenv("DEEPSEEK_THINKING") or "disabled").strip().lower()
	if value in {"1", "true", "yes", "on", "enabled"}:
		return "enabled"
	if value in {"0", "false", "no", "off", "disabled"}:
		return "disabled"
	return "disabled"


@lru_cache(maxsize=8)
def _get_openai_client_cached(base_url: str, api_key: str, headers_key: str, timeout: float):
	from openai import OpenAI

	default_headers = _get_sany_headers() if headers_key == "sany" else None
	kwargs: dict[str, Any] = {"api_key": api_key, "base_url": base_url, "timeout": timeout}
	if default_headers:
		kwargs["default_headers"] = default_headers
	return OpenAI(**kwargs)


def _get_chat_config(*, model: str | None = None) -> dict[str, Any]:
	route = getattr(trans, "ROUTE", "official")
	timeout = _get_env_float("DEEPSEEK_REQUEST_TIMEOUT", DEFAULT_REQUEST_TIMEOUT_SECONDS)

	if route == "sany":
		api_key = os.getenv("SANY_AI_GATEWAY_KEY") or os.getenv("SANY_AI_GATEWAY_API_KEY")
		if not api_key:
			raise RuntimeError("Missing SANY gateway api key. Set env var SANY_AI_GATEWAY_KEY.")
		base_url = _normalize_base_url(os.getenv("SANY_AI_GATEWAY_BASE_URL", "https://agent-api-test.sany.com.cn/ai-api"))
		model_name = (model or os.getenv("SANY_EXTRACT_MODEL") or DEFAULT_SANY_EXTRACT_MODEL).strip()
		return {
			"route": route,
			"api_key": api_key,
			"base_url": base_url,
			"model_name": model_name,
			"headers_key": "sany",
			"max_tokens": _get_env_int("SANY_STRUCTURED_MAX_TOKENS", DEFAULT_SANY_MAX_TOKENS),
			"timeout": timeout,
		}

	if route == "openai":
		api_key = os.getenv("OPENAI_API_KEY")
		if not api_key:
			raise RuntimeError("Missing OpenAI API key. Set env var OPENAI_API_KEY.")
		base_url = _normalize_base_url(os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
		model_name = (model or os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_EXTRACT_MODEL).strip()
		return {
			"route": route,
			"api_key": api_key,
			"base_url": base_url,
			"model_name": model_name,
			"headers_key": "none",
			"max_tokens": _get_env_int("DEEPSEEK_STRUCTURED_MAX_TOKENS", DEFAULT_STRUCTURED_MAX_TOKENS),
			"timeout": timeout,
		}

	# default: official (SiliconFlow)
	api_key = os.getenv("SILICONFLOW_API_KEY") or os.getenv("SILICONFLOW_KEY")
	if not api_key:
		raise RuntimeError("Missing SiliconFlow API key: set env var SILICONFLOW_API_KEY")
	base_url = _normalize_base_url(os.getenv("SILICONFLOW_BASE_URL", DEFAULT_SILICONFLOW_BASE_URL))
	model_name = (model or os.getenv("SILICONFLOW_EXTRACT_MODEL") or DEFAULT_SILICONFLOW_EXTRACT_MODEL).strip()

	return {
		"route": route,
		"api_key": api_key,
		"base_url": base_url,
		"model_name": model_name,
		"headers_key": "none",
		"max_tokens": _get_env_int("DEEPSEEK_STRUCTURED_MAX_TOKENS", DEFAULT_STRUCTURED_MAX_TOKENS),
		"timeout": timeout,
	}


def _schema_json(schema: type[Any]) -> dict[str, Any]:
	if hasattr(schema, "model_json_schema"):
		try:
			return schema.model_json_schema()
		except Exception:
			return {}
	return {}


def _example_from_json_schema(schema: dict[str, Any], defs: dict[str, Any] | None = None, *, depth: int = 0) -> Any:
	defs = defs or schema.get("$defs") or schema.get("definitions") or {}
	if depth > 4:
		return None

	if "$ref" in schema:
		ref_name = str(schema["$ref"]).rsplit("/", 1)[-1]
		return _example_from_json_schema(defs.get(ref_name, {}), defs, depth=depth + 1)

	if "anyOf" in schema:
		options = [s for s in schema.get("anyOf", []) if s.get("type") != "null"]
		return _example_from_json_schema(options[0], defs, depth=depth + 1) if options else None

	if "oneOf" in schema:
		options = schema.get("oneOf", [])
		return _example_from_json_schema(options[0], defs, depth=depth + 1) if options else None

	if "allOf" in schema:
		options = schema.get("allOf", [])
		return _example_from_json_schema(options[0], defs, depth=depth + 1) if options else None

	schema_type = schema.get("type")
	if schema_type == "object" or "properties" in schema:
		return {
			key: _example_from_json_schema(value, defs, depth=depth + 1)
			for key, value in (schema.get("properties") or {}).items()
		}
	if schema_type == "array":
		return [_example_from_json_schema(schema.get("items") or {}, defs, depth=depth + 1)]
	if schema_type == "boolean":
		return False
	if schema_type in {"integer", "number"}:
		return 0
	if schema_type == "string":
		return ""
	if isinstance(schema_type, list):
		for item_type in schema_type:
			if item_type != "null":
				return _example_from_json_schema({**schema, "type": item_type}, defs, depth=depth + 1)
	return None


def _json_output_instruction(schema: type[Any]) -> str:
	schema_dict = _schema_json(schema)
	example = _example_from_json_schema(schema_dict)
	if example in (None, {}):
		example = {"field": "value"}
	example_text = json.dumps(example, ensure_ascii=False, separators=(",", ":"))
	return (
		"Return only one valid json object. Do not include markdown, code fences, or explanation. "
		f"The json output must follow this example shape: {example_text}"
	)


def _with_json_output_instruction(messages: list[dict[str, str]], schema: type[Any]) -> list[dict[str, str]]:
	instruction = _json_output_instruction(schema)
	out = [dict(m) for m in (messages or [])]
	for message in out:
		if (message.get("role") or "").strip().lower() == "system":
			message["content"] = f"{message.get('content') or ''}\n\n{instruction}"
			return out
	return [{"role": "system", "content": instruction}, *out]


def _strip_json_code_fence(content: str) -> str:
	return _JSON_CODE_FENCE_RE.sub("", content.strip()).strip()


def _parse_json_content(content: str) -> Any:
	text = _strip_json_code_fence(content)
	try:
		return json.loads(text)
	except json.JSONDecodeError:
		start = text.find("{")
		end = text.rfind("}")
		if start >= 0 and end > start:
			return json.loads(text[start : end + 1])
		raise


def _validate_structured_result(data: Any, schema: type[T]) -> T:
	if hasattr(schema, "model_validate"):
		return schema.model_validate(data)
	return schema(**data)


def _create_structured_completion(
	messages: list[dict[str, str]],
	schema: type[T],
	*,
	model: str | None = None,
) -> T:
	config = _get_chat_config(model=model)
	client = _get_openai_client_cached(
		config["base_url"],
		config["api_key"],
		config["headers_key"],
		config["timeout"],
	)
	request_messages = _with_json_output_instruction(messages, schema)
	request_kwargs: dict[str, Any] = {
		"model": config["model_name"],
		"messages": request_messages,
		"temperature": 0,
		"max_tokens": config["max_tokens"],
		"response_format": {"type": "json_object"},
	}
	thinking_mode = _get_deepseek_structured_thinking_mode(config["base_url"])
	if thinking_mode:
		request_kwargs["extra_body"] = {"thinking": {"type": thinking_mode}}

	response: Any = client.chat.completions.create(**request_kwargs)
	content = (response.choices[0].message.content or "").strip()
	if not content:
		raise RuntimeError("DeepSeek JSON Output returned empty content. Retry with a more explicit JSON prompt.")
	return _validate_structured_result(_parse_json_content(content), schema)


def invoke_structured(messages: list[dict[str, str]], schema: type[T], *, model: str | None = None) -> T:
	"""
	Invoke DeepSeek (via OpenAI-compatible endpoints) with official JSON Output.

	Notes:
	- Only used for JSON-structured extraction/classification steps.
	- Uses response_format={"type": "json_object"} and validates locally with Pydantic.
	- Markdown/plain-text transformations keep using src.extract_client.chat_completion.
	"""
	return _create_structured_completion(messages, schema, model=model)


async def ainvoke_structured(messages: list[dict[str, str]], schema: type[T], *, model: str | None = None) -> T:
	"""
	Async variant of invoke_structured().

	The OpenAI SDK call is executed in a worker thread so FastAPI/browser workflows do
	not block the event loop while waiting on the provider.
	"""
	return await asyncio.to_thread(invoke_structured, messages, schema, model=model)


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
