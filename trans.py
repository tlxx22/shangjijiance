"""
Test-only LLM routing override.

Goal (as requested):
- Keep "official" behavior unchanged (browser-use cloud via ChatBrowserUse).
- When ROUTE="sany", DO NOT use SANY gateway for browser-use navigation; instead call
  browser-use cloud "bu-latest" with a hard-coded API key.
- DeepSeek extraction remains routed by `trans.ROUTE` in `src/extract_client.py`.
  So setting ROUTE="sany" here keeps extraction on SANY gateway while navigation uses cloud.

WARNING: This file contains a plaintext API key. Do not commit it to a shared repo.
"""

from __future__ import annotations

import os
from typing import Literal, cast

from browser_use.llm.base import BaseChatModel
from browser_use.llm.browser_use import ChatBrowserUse
from browser_use.llm.openai.chat import ChatOpenAI

# ======= Switch here =======
# - "official": browser-use cloud (original)
# - "sany": browser-use cloud for navigation, SANY gateway for DeepSeek extraction (via trans.ROUTE)
# - "openai": browser-use cloud for navigation, OpenAI-compatible endpoint for extraction (via src/extract_client.py)
#
# Runtime override:
# - Set env var TRANS_ROUTE to one of: official / sany / openai
_route_env = (os.getenv("TRANS_ROUTE") or "").strip().lower()
if _route_env in {"official", "sany", "openai"}:
	ROUTE: Literal["official", "sany", "openai"] = cast(Literal["official", "sany", "openai"], _route_env)
else:
	ROUTE: Literal["official", "sany", "openai"] = "openai"

# Navigation model (browser-use).
OFFICIAL_MODEL_NAME = "bu-2-0"

# Hard-coded API key for browser-use cloud when ROUTE="sany" (test only).
_BROWSER_USE_CLOUD_KEY_FOR_SANY = "bu_Ga_1Citdb1Gm7MrHKK8aYLMVCJWBFlhEKJIq5YqXwB8"


def build_llm() -> BaseChatModel:
	"""Build the LLM instance used by browser-use Agent (navigation/planning)."""
	if ROUTE == "official":
		return ChatBrowserUse(
			model=OFFICIAL_MODEL_NAME,
			api_key=os.getenv("BROWSER_USE_API_KEY"),
			base_url=os.getenv("BROWSER_USE_LLM_URL"),
		)

	if ROUTE == "sany":
		# Keep using browser-use cloud for navigation to avoid SANY-private model instability.
		return ChatBrowserUse(
			model=OFFICIAL_MODEL_NAME,
			api_key=_BROWSER_USE_CLOUD_KEY_FOR_SANY,
			base_url=os.getenv("BROWSER_USE_LLM_URL"),
		)

	if ROUTE == "openai":
		# Extraction uses OpenAI (see src/extract_client.py). Navigation stays on browser-use cloud.
		return ChatBrowserUse(
			model=OFFICIAL_MODEL_NAME,
			api_key=os.getenv("BROWSER_USE_API_KEY"),
			base_url=os.getenv("BROWSER_USE_LLM_URL"),
		)

	raise ValueError(f"Unknown ROUTE={ROUTE!r}. Expected 'official' or 'sany' or 'openai'.")
