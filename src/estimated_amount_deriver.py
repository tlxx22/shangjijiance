from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, MutableMapping

from .estimated_amount_policy import apply_estimated_amount_policy
from .logger_config import get_logger

logger = get_logger()


Extractor = Callable[..., Awaitable[dict[str, Any]]]


def build_estimated_amount_source_text(
	*,
	lot_products: list[dict],
	announcement_content: str,
	excerpt_len: int = 12000,
) -> str:
	lot_products_json = json.dumps(lot_products or [], ensure_ascii=False)
	body_excerpt = str(announcement_content or "").strip()[: max(0, int(excerpt_len or 0))]

	text = (
		"标的物(lotProducts JSON): "
		+ lot_products_json
	).strip()
	if body_excerpt:
		text += "\n\n正文补充(仅供识别会直接约束金额区间的价格边界信息，例如最高限价/最低限价/控制价/起拍价/保留价等；不要根据正文重新补标的物，其它正文内容请忽略): " + body_excerpt
	text += "\n\n注意: 标的物信息只以 lotProducts 为准；不要根据正文重新识别、补写或改写标的物、数量、型号。若 lotProducts 中出现单价/数量/总价为 0 等明显占位值，默认视为未知，不能直接把 0 当作估价下限。你必须基于同类标的物在真实市场中的采购/成交价格进行估算；若标的物类型可识别，下限必须是按真实市场价格实际可采购的合理下限，不能为了满足格式随意给出 0、1 或其它明显失真的极小值。你可以自行识别正文中任何会直接约束金额范围的价格边界信息，并据此收窄或修正估价区间；忽略非金额范围（如 1.4~3m3）以及联系人、电话、日期、流程、资格要求、候选单位、排名得分等无关信息。"
	return text.strip()


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
	4) Otherwise, call extractor(stage="estimated_amount") once based on lotProducts plus a body excerpt.
	   After the call, apply policy again.
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

	try:
		text = build_estimated_amount_source_text(
			lot_products=[x for x in lot_products if isinstance(x, dict)],
			announcement_content=str(item.get("announcementContent") or ""),
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
		logger.warning(f"[{site_name}] estimatedAmount 派生 LLM 调用失败: {e}")

	try:
		apply_estimated_amount_policy(item)
	except Exception:
		return

	# Still empty after retries: keep empty (no exception).
	return

