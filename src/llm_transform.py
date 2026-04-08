from __future__ import annotations

import asyncio
import re
from typing import Any

from .algorithm_version import ALGORITHM_VERSION
from .config_manager import load_extract_fields
from .custom_tools import extract_fields_from_text, normalize_field_value
from .extract_client import chat_completion
from .field_schemas import supplement_lot_products_from_candidates, try_normalize_announcement_type


def _strip_code_fences(text: str) -> str:
	"""
	LLM 偶尔会输出 ```json / ```markdown 包裹，这里做轻量剥离。
	"""
	s = (text or "").strip()
	if s.startswith("```"):
		lines = s.splitlines()
		if lines:
			lines = lines[1:]
		while lines and lines[-1].strip().startswith("```"):
			lines.pop()
		s = "\n".join(lines).strip()
	return s


_MD_ESC_RE = re.compile(r"(?<!\\)\\([nrt])")


def _unescape_md_control_sequences(text: str) -> str:
	"""
	DeepSeek 有时会把换行写成字面量 "\\n"，导致粘贴到 Typora 变成一整块。
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
	Fields come from extract_fields.yaml (all stages) plus announcementUrl/Name/Content, dataId, and version.
	"""
	out: dict[str, Any] = {
		"dataId": "",
		"version": ALGORITHM_VERSION,
		"inputTruncated": False,
		"announcementUrl": "",
		"announcementName": "",
		"announcementContent": "",
	}

	for f in load_extract_fields(stage=None):
		out.setdefault(f.key, _TYPE_DEFAULTS.get(f.type, ""))

	if "isEquipment" in out:
		out["isEquipment"] = True

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

	item: dict[str, Any] = dict(template)
	for key in template.keys():
		if key in raw_item:
			item[key] = raw_item[key]

	item["announcementUrl"] = ("" if item.get("announcementUrl") is None else str(item.get("announcementUrl"))).strip()
	item["announcementName"] = ("" if item.get("announcementName") is None else str(item.get("announcementName"))).strip()
	item["announcementContent"] = ("" if item.get("announcementContent") is None else str(item.get("announcementContent"))).strip()
	item["inputTruncated"] = bool(item.get("inputTruncated", False))

	for field in load_extract_fields(stage=None):
		item[field.key] = normalize_field_value(field.key, item.get(field.key), field.type)

	item["lotProducts"] = supplement_lot_products_from_candidates(
		item.get("lotProducts"),
		item.get("lotCandidates"),
	)
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
	from .normalize_item_graph import run_normalize_item_core_graph

	return await run_normalize_item_core_graph(
		source_json,
		product_category_table=product_category_table,
	)
