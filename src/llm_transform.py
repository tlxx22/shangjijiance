from __future__ import annotations

import asyncio
import re
from typing import Any

from .extract_client import chat_completion
from .config_manager import load_extract_fields
from .custom_tools import extract_fields_from_text, normalize_field_value
from .announcement_type_repair import AnnouncementTypeRepairError, repair_announcement_type
from .estimated_amount_policy import apply_estimated_amount_policy
from .field_schemas import (
	ANNOUNCEMENT_TYPES,
	try_normalize_announcement_type,
)


def _strip_code_fences(text: str) -> str:
	"""
	LLM 偶尔会输出 ```json / ```markdown 包裹，这里做轻量剥离。
	"""
	s = (text or "").strip()
	if s.startswith("```"):
		# remove first fence line
		lines = s.splitlines()
		if lines:
			lines = lines[1:]
		# remove trailing fence
		while lines and lines[-1].strip().startswith("```"):
			lines.pop()
		s = "\n".join(lines).strip()
	return s


_MD_ESC_RE = re.compile(r"(?<!\\)\\([nrt])")


def _unescape_md_control_sequences(text: str) -> str:
	"""
	DeepSeek 有时会把换行写成字面量的 "\\n"（两个字符），导致粘贴到 Typora 变成一整块。
	这里把常见控制序列还原成真实字符（仅处理未被转义的 \\n/\\r/\\t）。
	"""
	def repl(m: re.Match[str]) -> str:
		ch = m.group(1)
		if ch == "n":
			return "\n"
		if ch == "r":
			return "\r"
		return "\t"

	return _MD_ESC_RE.sub(repl, text or "")


_TYPE_DEFAULTS: dict[str, Any] = {
	"string": "",
	"number": None,
	"boolean": False,
	"array": [],
}


def _build_full_item_template() -> dict[str, Any]:
	"""
	Build a full item template that matches the crawler output structure.
	Fields come from extract_fields.yaml (all stages) plus announcementUrl/Name/Content and dataId.
	"""
	out: dict[str, Any] = {
		"dataId": "",
		"announcementUrl": "",
		"announcementName": "",
		"announcementContent": "",
	}

	# Keep field definitions identical to crawler extraction config.
	for f in load_extract_fields(stage=None):
		out.setdefault(f.key, _TYPE_DEFAULTS.get(f.type, ""))

	return out


def _normalize_item_to_crawler_schema(raw_item: dict[str, Any]) -> dict[str, Any]:
	"""
	Apply the same normalization behavior as crawler output:
	- Ensure all keys exist with correct empty defaults
	- Normalize types/dates/money formats (via normalize_field_value)
	- Normalize lotProducts/lotCandidates to strict schema (drop extra keys)
	- Normalize announcementType
	"""
	template = _build_full_item_template()

	# Merge known keys only.
	item: dict[str, Any] = dict(template)
	for k in template.keys():
		if k in raw_item:
			item[k] = raw_item[k]

	# Now normalize by type using the exact extract_fields.yaml field types (flat + lots).
	# announcementUrl/Name/Content are always strings.
	item["announcementUrl"] = ("" if item.get("announcementUrl") is None else str(item.get("announcementUrl"))).strip()
	item["announcementName"] = ("" if item.get("announcementName") is None else str(item.get("announcementName"))).strip()
	item["announcementContent"] = ("" if item.get("announcementContent") is None else str(item.get("announcementContent"))).strip()

	for f in load_extract_fields(stage=None):
		item[f.key] = normalize_field_value(f.key, item.get(f.key), f.type)

	item["announcementType"] = try_normalize_announcement_type(item.get("announcementType")) or ""
	return item


async def _extract_normalize_item_fields(
	src_text: str,
	*,
	stage: str,
	product_category_table: str | None,
) -> dict[str, Any]:
	"""
	/normalize_item 专用：按 stage 抽取字段（使用独立 YAML 配置）。
	"""
	text = (src_text or "").strip()
	if not text:
		# Let extract_fields_from_text return the correct empty_result by stage.
		return await extract_fields_from_text(
			"",
			site_name="normalize_item",
			stage=stage,
			fields_path="normalize_item_meta_flat_fields.yaml",
			product_category_table=product_category_table,
		)

	return await extract_fields_from_text(
		text,
		site_name="normalize_item",
		stage=stage,
		fields_path="normalize_item_meta_flat_fields.yaml",
		product_category_table=product_category_table,
	)


async def convert_announcement_content_to_markdown(announcement_content: str) -> str:
	"""
	Convert cleaned announcementContent (typically HTML) to a structured Markdown text using DeepSeek.
	Routing is controlled by trans.ROUTE via extract_client.chat_completion.
	"""
	content = (announcement_content or "").strip()
	if not content:
		return ""

	system_prompt = """
You are a document formatter.
You will be given an already-cleaned tender/notice announcement content (usually HTML, sometimes plain text).
Convert it into well-structured Markdown that preserves meaning and structure.

Rules:
- Output ONLY Markdown (no JSON, no explanations).
- Preserve headings and section order; use #/##/### appropriately.
- Convert tables to Markdown tables when feasible; if too wide/irregular, use bullet lists instead.
- Keep important numbers/dates/amounts exactly as-is; do not invent content.
- Remove pure styling noise (font/size/line-height artifacts); keep readable text.
""".strip()

	user_prompt = f"announcementContent:\\n{content}"
	out = await asyncio.to_thread(
		chat_completion,
		[
			{"role": "system", "content": system_prompt},
			{"role": "user", "content": user_prompt},
		],
	)
	md = _strip_code_fences(out)
	return _unescape_md_control_sequences(md)


async def normalize_source_json_to_item(
	source_json: str,
	*,
	product_category_table: str | None = None,
) -> dict[str, Any]:
	"""
	Map arbitrary source JSON/text into our unified item template via multi-stage extraction:
	- meta / contacts / address_detail / lots
	(lots is a single call that outputs both lotProducts + lotCandidates)

	Input is a raw text string (often a JSON blob mixed with other text). We feed it directly to the extractor.
	"""
	src = (source_json or "").strip()
	template = _build_full_item_template()
	if not src:
		return template

	meta_fields, contacts_fields, address_detail_fields, lots_fields = await asyncio.gather(
		_extract_normalize_item_fields(src, stage="meta", product_category_table=None),
		_extract_normalize_item_fields(src, stage="contacts", product_category_table=None),
		_extract_normalize_item_fields(src, stage="address_detail", product_category_table=None),
		_extract_normalize_item_fields(src, stage="lots", product_category_table=product_category_table),
	)

	merged = dict(template)
	merged.update(meta_fields or {})
	merged.update(contacts_fields or {})
	merged.update(address_detail_fields or {})
	merged["lotProducts"] = (lots_fields or {}).get("lotProducts") or []
	merged["lotCandidates"] = (lots_fields or {}).get("lotCandidates") or []

	raw_announcement_type = (meta_fields or {}).get("announcementType")
	item = _normalize_item_to_crawler_schema(merged)

	# 公告类别（13 选 1）强校验：
	# - 不再“无法映射就兜底成招标”
	# - 如果初次抽取不在范围内：调用 DeepSeek 做一次“类型归一化/分类”修复（最多 3 次）
	if (item.get("announcementType") or "").strip() not in ANNOUNCEMENT_TYPES:
		repaired = await repair_announcement_type(
			site_name="normalize_item",
			announcement_title=item.get("announcementName"),
			announcement_content=item.get("announcementContent") or src,
			raw_announcement_type=str(raw_announcement_type or merged.get("announcementType") or ""),
			max_retries=3,
		)
		if not repaired:
			raise AnnouncementTypeRepairError(
				"announcementType invalid after 3 attempts",
				raw_type=str(raw_announcement_type or merged.get("announcementType") or ""),
				max_retries=3,
			)
		item["announcementType"] = repaired

	# estimatedAmount：
	# - 与 announcementType 无关。
	# - 仅由“中标金额/候选人报价/标的物”决定：
	#   1) 若有中标金额：直接取中标金额（输出范围 "x~x"）
	#      - 优先 winnerAmount
	#      - 其次第一位中标/中标候选人报价（lotCandidates[].candidatePrices）
	#   2) 若无中标金额但有标的物：保留 LLM 预估价（需为范围 "lo~hi"）
	#   3) 若无中标金额且无标的物：返回 ""
	# 本阶段只做：按上述优先级覆盖/清空 + 正则校验（不做任何兜底/推导/再调用）。
	apply_estimated_amount_policy(item)

	return item
