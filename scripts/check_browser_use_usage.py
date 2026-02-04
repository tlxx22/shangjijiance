from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

try:
	from dotenv import load_dotenv

	load_dotenv()
except Exception:
	pass

from browser_use.llm.browser_use import ChatBrowserUse
from browser_use.llm.messages import SystemMessage, UserMessage


def _safe_stdout_utf8() -> None:
	try:
		sys.stdout.reconfigure(encoding="utf-8")
	except Exception:
		pass


def _usage_dict(usage) -> dict:
	if usage is None:
		return {"usage": None}
	return {
		"prompt_tokens": getattr(usage, "prompt_tokens", None),
		"prompt_cached_tokens": getattr(usage, "prompt_cached_tokens", None),
		"completion_tokens": getattr(usage, "completion_tokens", None),
		"total_tokens": getattr(usage, "total_tokens", None),
	}


async def main() -> int:
	_safe_stdout_utf8()

	parser = argparse.ArgumentParser(
		description="Check whether browser-use cloud responses include token usage, and optionally compute cost."
	)
	parser.add_argument("--model", default=os.getenv("BROWSER_USE_MODEL") or "bu-2-0")
	parser.add_argument("--base-url", default=os.getenv("BROWSER_USE_LLM_URL") or None)
	parser.add_argument("--api-key", default=os.getenv("BROWSER_USE_API_KEY") or None)
	parser.add_argument("--session-id", default=os.getenv("BROWSER_USE_SESSION_ID") or None)
	parser.add_argument("--n", type=int, default=1, help="number of invocations")
	parser.add_argument(
		"--cost",
		action="store_true",
		help="try to compute cost via browser_use TokenCost service (requires pricing mapping for the model)",
	)
	args = parser.parse_args()

	llm = ChatBrowserUse(model=args.model, api_key=args.api_key, base_url=args.base_url)

	token_cost_service = None
	if args.cost:
		from browser_use.tokens.service import TokenCost

		token_cost_service = TokenCost(include_cost=True)
		await token_cost_service.initialize()
		token_cost_service.register_llm(llm)

	messages = [
		SystemMessage(
			content=(
				"You are a concise API. Reply with ONLY one JSON object.\n"
				"Return keys: ok (boolean), echo (string). No extra text."
			)
		),
		UserMessage(content="echo=browser-use-usage-check"),
	]

	start = datetime.now(timezone.utc)
	results: list[dict] = []
	for i in range(args.n):
		kwargs = {}
		if args.session_id:
			kwargs["session_id"] = args.session_id

		r = await llm.ainvoke(messages, output_format=None, request_type="browser_agent", **kwargs)
		results.append(
			{
				"i": i + 1,
				"model": llm.model,
				"completion_preview": (str(r.completion)[:200] if r.completion is not None else ""),
				**_usage_dict(r.usage),
			}
		)

	out = {
		"ts": start.isoformat(),
		"base_url": llm.base_url,
		"model": llm.model,
		"invocations": results,
	}

	if token_cost_service is not None:
		summary = await token_cost_service.get_usage_summary(since=start)
		out["token_cost_summary"] = summary.model_dump()

	print(json.dumps(out, ensure_ascii=False, indent=2))
	return 0


if __name__ == "__main__":
	raise SystemExit(asyncio.run(main()))
