from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, MutableMapping

from .estimated_amount_policy import apply_estimated_amount_policy
from .logger_config import get_logger

logger = get_logger()


Extractor = Callable[..., Awaitable[dict[str, Any]]]


def build_estimated_amount_source_text(
	*,
	announcement_name: str,
	announcement_content: str,
	lot_products: list[dict],
	excerpt_len: int,
) -> str:
	title = (announcement_name or "").strip()
	content = (announcement_content or "").strip()
	excerpt = content[: max(0, int(excerpt_len or 0))]
	lot_products_json = json.dumps(lot_products or [], ensure_ascii=False)

	return (
		"公告标题: "
		+ title
		+ "\n\n"
		+ "正文节选: "
		+ excerpt
		+ "\n\n"
		+ "标的物(lotProducts JSON): "
		+ lot_products_json
		+ "\n\n"
		+ "注意: lotProducts 为结构化结果，优先使用；忽略 1.4~3m3 等非金额范围。"
	).strip()


async def fill_estimated_amount_after_lots(
	item: MutableMapping[str, Any],
	*,
	site_name: str,
	fields_path: str,
	extractor: Extractor | None = None,
) -> None:
	"""
	Derive estimatedAmount AFTER lotProducts/lotCandidates are finalized.

	Algorithm:
	1) Apply policy (winner/candidate override + validation).
	2) If estimatedAmount exists -> done.
	3) If no lotProducts -> done (keep empty).
	4) Otherwise, call extractor(stage="estimated_amount") at most twice:
	   - excerpt_len=3000
	   - retry excerpt_len=12000
	   After each call, apply policy again.
	"""
	try:
		apply_estimated_amount_policy(item)
	except Exception:
		# Must never break upstream flows.
		return

	if str(item.get("estimatedAmount") or "").strip():
		return

	lot_products = item.get("lotProducts") or []
	if not isinstance(lot_products, list) or not lot_products:
		return

	if extractor is None:
		try:
			from .custom_tools import extract_fields_from_text as extractor  # local import to avoid cycles
		except Exception as e:
			logger.warning(f"[{site_name}] estimatedAmount 派生初始化失败（extractor import）: {e}")
			return

	announcement_name = str(item.get("announcementName") or "")
	announcement_content = str(item.get("announcementContent") or "")

	for excerpt_len in (3000, 12000):
		try:
			text = build_estimated_amount_source_text(
				announcement_name=announcement_name,
				announcement_content=announcement_content,
				lot_products=[x for x in lot_products if isinstance(x, dict)],
				excerpt_len=excerpt_len,
			)
			out = await extractor(
				text,
				site_name=site_name,
				stage="estimated_amount",
				fields_path=fields_path,
				product_category_table=None,
			)
			if isinstance(out, dict):
				item["estimatedAmount"] = out.get("estimatedAmount", item.get("estimatedAmount"))
		except Exception as e:
			logger.warning(f"[{site_name}] estimatedAmount 派生 LLM 调用失败（excerpt_len={excerpt_len}）: {e}")
			# swallow and keep trying or fallback to empty
		try:
			apply_estimated_amount_policy(item)
		except Exception:
			return

		if str(item.get("estimatedAmount") or "").strip():
			return

	# Still empty after retries: keep empty (no exception).
	return
