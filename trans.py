"""
LLM routing switch.

Edit ROUTE below to switch between:
- "official": browser-use official cloud API (ChatBrowserUse)
- "sany": SANY AI Gateway (OpenAI-compatible /ai-api/chat/completions, ChatOpenAI)
"""

from __future__ import annotations

import os
from typing import Literal

from browser_use.llm.base import BaseChatModel
from browser_use.llm.browser_use import ChatBrowserUse
from browser_use.llm.openai.chat import ChatOpenAI

# ======= Switch here =======
# - "official": keep the original behavior (browser-use cloud)
# - "sany": call SANY AI Gateway (OpenAI-compatible)
ROUTE: Literal["official", "sany"] = "official"

# Model names (hard-coded as requested; do not use env vars).
# - official: browser-use cloud
# - sany: SANY gateway (OpenAI-compatible)
OFFICIAL_MODEL_NAME = "bu-latest"
SANY_MODEL_NAME = "bu-30b-a3b-preview"


def build_llm() -> BaseChatModel:
	"""Build the LLM instance used by browser-use Agent."""
	if ROUTE == "official":
		# browser-use Cloud (original behavior)
		# - API Key: BROWSER_USE_API_KEY
		# - Base URL: BROWSER_USE_LLM_URL (optional, defaults to https://llm.api.browser-use.com)
		return ChatBrowserUse(
			model=OFFICIAL_MODEL_NAME,
			api_key=os.getenv("BROWSER_USE_API_KEY"),
			base_url=os.getenv("BROWSER_USE_LLM_URL"),
		)

	if ROUTE == "sany":
		# SANY gateway: OpenAI-compatible /ai-api/chat/completions
		# - API Key: SANY_AI_GATEWAY_KEY (or SANY_AI_GATEWAY_API_KEY)
		# - Base URL: SANY_AI_GATEWAY_BASE_URL (defaults to test env)
		api_key = os.getenv("SANY_AI_GATEWAY_KEY") or os.getenv("SANY_AI_GATEWAY_API_KEY")
		if not api_key:
			raise ValueError(
				"Missing SANY gateway api key. Set env var SANY_AI_GATEWAY_KEY (Authorization: Bearer <key>)."
			)

		base_url = os.getenv("SANY_AI_GATEWAY_BASE_URL", "https://agent-api-test.sany.com.cn/ai-api")

		# Optional: force gateway vendor routing (header X-ai-server)
		default_headers: dict[str, str] = {}
		x_ai_server = os.getenv("SANY_X_AI_SERVER") or os.getenv("SANY_AI_SERVER")
		if x_ai_server:
			default_headers["X-ai-server"] = x_ai_server

		# Note:
		# Some OpenAI-compatible gateways do NOT support response_format(json_schema).
		# For max compatibility we embed the schema into the system prompt and do not
		# force response_format.
		return ChatOpenAI(
			model=SANY_MODEL_NAME,
			api_key=api_key,
			base_url=base_url,
			default_headers=default_headers or None,
			add_schema_to_system_prompt=True,
			dont_force_structured_output=True,
		)

	raise ValueError(f"Unknown ROUTE={ROUTE!r}. Expected 'official' or 'sany'.")
