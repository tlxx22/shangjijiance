from __future__ import annotations

import os
from typing import Any

from openai import OpenAI

import trans


DEFAULT_SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_SILICONFLOW_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"
DEFAULT_SILICONFLOW_EMBEDDING_DIMENSIONS = 2048
DEFAULT_SILICONFLOW_EMBEDDING_ENCODING_FORMAT = "float"

DEFAULT_SANY_EMBEDDING_MODEL = "text-embedding-v4"
DEFAULT_SANY_EMBEDDING_DIMENSIONS = 2048
DEFAULT_SANY_EMBEDDING_ENCODING_FORMAT = "float"


def _map_backend_embedding_model(model_name: str, *, route: str) -> str:
	"""
	Backend compatibility mapping.

	- Yaowu backend may send "text-embedding-v4" (with or without leading/trailing spaces)
	  while the actual deployed embedding model is "Qwen/Qwen3-Embedding-8B".
	- Only apply this mapping for non-SANY routes.
	"""
	m = (model_name or "").strip()
	if route != "sany" and m == "text-embedding-v4":
		return DEFAULT_SILICONFLOW_EMBEDDING_MODEL
	return m


def _normalize_sany_ali_base_url(base_url: str) -> str:
	"""
	The SANY gateway embeddings endpoint is under /ai-api/ali/embeddings.

	OpenAI SDK expects base_url without the trailing endpoint path, so:
	- If input is https://.../ai-api -> use https://.../ai-api/ali
	- If input is https://.../ai-api/ali -> keep
	"""
	u = (base_url or "").rstrip("/")
	if not u:
		return u
	if u.endswith("/ai-api/ali"):
		return u
	if u.endswith("/ai-api"):
		return f"{u}/ali"
	# allow passing full /ai-api/ali/embeddings accidentally
	if u.endswith("/ai-api/ali/embeddings"):
		return u[: -len("/embeddings")]
	return u


def _ensure_embedding_dimensions(embedding: list[float], dims: int) -> list[float]:
	"""
	Ensure returned embedding vector is exactly `dims` long.

	- If longer: truncate
	- If shorter: right-pad with 0.0
	"""
	if dims <= 0:
		return embedding
	if len(embedding) == dims:
		return embedding
	if len(embedding) > dims:
		return embedding[:dims]
	return embedding + [0.0] * (dims - len(embedding))


def get_text_embedding(
	text: str,
	*,
	model: str | None = None,
	dimensions: int | None = None,
	encoding_format: str | None = None,
) -> tuple[str, list[float]]:
	"""
	Get an embedding vector for the given text.

	Routing:
	- trans.ROUTE == "official": SiliconFlow (OpenAI-compatible /v1/embeddings)
	- trans.ROUTE == "sany": SANY gateway (OpenAI-compatible /ai-api/ali/embeddings)

	Returns:
	  (model_name, embedding_vector)
	"""
	text = (text or "").strip()
	if not text:
		raise ValueError("text is empty")

	route = getattr(trans, "ROUTE", "official")

	if route == "sany":
		api_key = os.getenv("SANY_AI_GATEWAY_KEY") or os.getenv("SANY_AI_GATEWAY_API_KEY")
		if not api_key:
			raise RuntimeError("Missing SANY gateway api key. Set env var SANY_AI_GATEWAY_KEY.")

		base_url = os.getenv("SANY_AI_GATEWAY_BASE_URL", "https://agent-api-test.sany.com.cn/ai-api")
		base_url = _normalize_sany_ali_base_url(base_url)

		model_name = (model or os.getenv("SANY_EMBEDDING_MODEL") or DEFAULT_SANY_EMBEDDING_MODEL).strip()
		dims = dimensions or int(os.getenv("SANY_EMBEDDING_DIMENSIONS") or DEFAULT_SANY_EMBEDDING_DIMENSIONS)
		enc = (encoding_format or os.getenv("SANY_EMBEDDING_ENCODING_FORMAT") or DEFAULT_SANY_EMBEDDING_ENCODING_FORMAT).strip()

		client = OpenAI(api_key=api_key, base_url=base_url)
		try:
			resp: Any = client.embeddings.create(model=model_name, input=text, dimensions=dims, encoding_format=enc)
		except Exception:
			# Some OpenAI-compatible providers/models may not support (dimensions, encoding_format).
			# Fall back to a plain request and then shape the vector to the requested length.
			resp = client.embeddings.create(model=model_name, input=text)
		embedding = resp.data[0].embedding
		return model_name, _ensure_embedding_dimensions(embedding, dims)

	# default: official
	api_key = os.getenv("SILICONFLOW_API_KEY") or os.getenv("SILICONFLOW_KEY")
	if not api_key:
		raise RuntimeError("Missing SiliconFlow API key: set env var SILICONFLOW_API_KEY")

	base_url = os.getenv("SILICONFLOW_BASE_URL", DEFAULT_SILICONFLOW_BASE_URL).strip()
	model_name = (model or os.getenv("SILICONFLOW_EMBEDDING_MODEL") or DEFAULT_SILICONFLOW_EMBEDDING_MODEL).strip()
	model_name = _map_backend_embedding_model(model_name, route=route)
	dims = dimensions or int(os.getenv("SILICONFLOW_EMBEDDING_DIMENSIONS") or DEFAULT_SILICONFLOW_EMBEDDING_DIMENSIONS)
	enc = (encoding_format or os.getenv("SILICONFLOW_EMBEDDING_ENCODING_FORMAT") or DEFAULT_SILICONFLOW_EMBEDDING_ENCODING_FORMAT).strip()

	client = OpenAI(api_key=api_key, base_url=base_url)
	try:
		resp: Any = client.embeddings.create(model=model_name, input=text, dimensions=dims, encoding_format=enc)
	except Exception:
		# Some OpenAI-compatible providers/models may not support (dimensions, encoding_format).
		# Fall back to a plain request and then shape the vector to the requested length.
		resp = client.embeddings.create(model=model_name, input=text)

	# OpenAI-compatible response: resp.data[0].embedding -> list[float]
	embedding = resp.data[0].embedding
	return model_name, _ensure_embedding_dimensions(embedding, dims)
