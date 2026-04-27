"""
LLM routing switch.

Runtime route is controlled by env var TRANS_ROUTE:
- "openai": Yaowu/default environment. Browser navigation uses browser-use cloud;
  extraction uses OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL via src.extract_client.
- "sany": SANY cloud desktop. Browser navigation and extraction use SANY AI Gateway.
- "official": legacy route. Browser navigation uses browser-use cloud; extraction uses SiliconFlow.
"""

from __future__ import annotations

import os
from typing import Literal, cast

from browser_use.llm.base import BaseChatModel
from browser_use.llm.browser_use import ChatBrowserUse
from browser_use.llm.openai.chat import ChatOpenAI

Route = Literal["official", "sany", "openai"]

# ======= Runtime switch =======
# Operations should set TRANS_ROUTE explicitly:
# - Yaowu server: TRANS_ROUTE=openai
# - SANY cloud desktop: TRANS_ROUTE=sany
_VALID_ROUTES = {"official", "sany", "openai"}
_route_env = (os.getenv("TRANS_ROUTE") or "").strip().lower()
if _route_env in _VALID_ROUTES:
	ROUTE: Route = cast(Route, _route_env)
else:
	ROUTE: Route = "openai"

# Model names are intentionally stable defaults. Extraction model overrides are
# handled in src.extract_client / src.deepseek_langchain, not here.
OFFICIAL_MODEL_NAME = "bu-2-0"
SANY_MODEL_NAME = "bu-2-0"


def _get_sany_headers() -> dict[str, str] | None:
	# Optional: force gateway vendor routing (header X-ai-server).
	x_ai_server = os.getenv("SANY_X_AI_SERVER") or os.getenv("SANY_AI_SERVER")
	if not x_ai_server:
		return None
	return {"X-ai-server": x_ai_server}


def _build_browser_use_cloud_llm() -> BaseChatModel:
	return ChatBrowserUse(
		model=OFFICIAL_MODEL_NAME,
		api_key=os.getenv("BROWSER_USE_API_KEY"),
		base_url=os.getenv("BROWSER_USE_LLM_URL"),
	)


def _build_sany_gateway_llm() -> BaseChatModel:
	api_key = os.getenv("SANY_AI_GATEWAY_KEY") or os.getenv("SANY_AI_GATEWAY_API_KEY")
	if not api_key:
		raise ValueError(
			"Missing SANY gateway api key. Set env var SANY_AI_GATEWAY_KEY "
			"(Authorization: Bearer <key>)."
		)

	base_url = os.getenv("SANY_AI_GATEWAY_BASE_URL", "https://agent-api-test.sany.com.cn/ai-api")

	# SANY gateway is OpenAI-compatible. Some compatible gateways do not support
	# response_format(json_schema), so keep structured-output schema in prompt.
	return ChatOpenAI(
		model=SANY_MODEL_NAME,
		api_key=api_key,
		base_url=base_url,
		default_headers=_get_sany_headers(),
		add_schema_to_system_prompt=True,
		dont_force_structured_output=True,
	)


def build_llm() -> BaseChatModel:
	"""Build the LLM instance used by browser-use Agent."""
	if ROUTE == "sany":
		return _build_sany_gateway_llm()

	if ROUTE in {"official", "openai"}:
		return _build_browser_use_cloud_llm()

	raise ValueError(f"Unknown ROUTE={ROUTE!r}. Expected 'official', 'sany', or 'openai'.")
