from __future__ import annotations

import os
from typing import Any

from openai import OpenAI


DEFAULT_SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_SILICONFLOW_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-8B"


def get_text_embedding(text: str, *, model: str | None = None) -> tuple[str, list[float]]:
	"""
	Get an embedding vector for the given text via SiliconFlow (OpenAI-compatible).

	Returns:
	  (model_name, embedding_vector)
	"""
	text = (text or "").strip()
	if not text:
		raise ValueError("text is empty")

	api_key = os.getenv("SILICONFLOW_API_KEY") or os.getenv("SILICONFLOW_KEY")
	if not api_key:
		raise RuntimeError("Missing SiliconFlow API key: set env var SILICONFLOW_API_KEY")

	base_url = os.getenv("SILICONFLOW_BASE_URL", DEFAULT_SILICONFLOW_BASE_URL).strip()
	model_name = (model or os.getenv("SILICONFLOW_EMBEDDING_MODEL") or DEFAULT_SILICONFLOW_EMBEDDING_MODEL).strip()

	client = OpenAI(api_key=api_key, base_url=base_url)
	resp: Any = client.embeddings.create(model=model_name, input=text)

	# OpenAI-compatible response: resp.data[0].embedding -> list[float]
	embedding = resp.data[0].embedding
	return model_name, embedding
