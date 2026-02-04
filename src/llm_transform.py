from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from .extract_client import chat_completion
from .config_manager import load_extract_fields
from .custom_tools import extract_fields_from_html, normalize_field_value
from .field_schemas import LotProducts, LotCandidates, normalize_announcement_type


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
	Fields come from extract_fields.yaml (flat + lots) plus announcementUrl/Name/Content and dataId.
	"""
	out: dict[str, Any] = {
		"dataId": "",
		"announcementUrl": "",
		"announcementName": "",
		"announcementContent": "",
	}

	# Keep field definitions identical to crawler extraction config.
	for stage in ("flat", "lots"):
		for f in load_extract_fields(stage=stage):
			# lots stage includes lotProducts/lotCandidates keys (array); flat stage includes strings/numbers/booleans.
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

	for stage in ("flat", "lots"):
		for f in load_extract_fields(stage=stage):
			item[f.key] = normalize_field_value(f.key, item.get(f.key), f.type)

	item["announcementType"] = normalize_announcement_type(item.get("announcementType"))
	return item


async def _extract_normalize_item_meta_via_llm(src_text: str) -> dict[str, str]:
	"""
	Extract crawler-level meta fields from an unstructured source string using DeepSeek.

	NOTE: We do NOT attempt to parse/understand the JSON structure locally here. The input is treated
	as plain text (may include JSON fragments, key-value dumps, etc).
	"""
	text = (src_text or "").strip()
	if not text:
		return {
			"announcementUrl": "",
			"announcementName": "",
			"announcementContent": "",
			"buyerAddressDetail": "",
			"projectAddressDetail": "",
			"deliveryAddressDetail": "",
		}

	system_prompt = """
You are an information extraction engine.
You will be given an unstructured text blob coming from 3rd-party bid sources (often a JSON string, but not guaranteed).
Extract the following fields and return ONLY valid JSON (no markdown, no code fences, no extra text).

Fields (all strings):
{
  "announcementUrl": "",
  "announcementName": "",
  "announcementContent": "",
  "buyerAddressDetail": "",
  "projectAddressDetail": "",
  "deliveryAddressDetail": ""
}

Rules:
- Do NOT guess. If a field cannot be found confidently, output "".
- If there are multiple URLs, prefer the one that looks like the original notice/detail page (not an index page).
- announcementName should be the notice title if present.
- announcementContent should be the notice body/detail text if present; do NOT dump the entire input text.
- For *AddressDetail: if there is no full address but there are province/city/district tokens, you may assemble a minimal address text by concatenating them (province+city+district).
- Address names must be full-form:
  - Provinces use “xx省”; Municipalities use “北京市/天津市/上海市/重庆市”
  - Autonomous regions use full names like “内蒙古自治区...”
  - Taiwan MUST be “中国台湾”
  - Cities end with 市/州/盟/地区 when applicable
  - Districts end with 区/县/市/旗 when applicable (if present in text)
""".strip()

	user_prompt = f"SOURCE_TEXT:\\n{text}"
	out = await asyncio.to_thread(
		chat_completion,
		[
			{"role": "system", "content": system_prompt},
			{"role": "user", "content": user_prompt},
		],
	)
	out = _strip_code_fences(out)

	default = {
		"announcementUrl": "",
		"announcementName": "",
		"announcementContent": "",
		"buyerAddressDetail": "",
		"projectAddressDetail": "",
		"deliveryAddressDetail": "",
	}
	try:
		parsed = json.loads(out)
		if not isinstance(parsed, dict):
			return default
	except Exception:
		return default

	normalized: dict[str, str] = dict(default)
	for k in default.keys():
		v = parsed.get(k, "")
		normalized[k] = "" if v is None else str(v).strip()
	return normalized


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


async def normalize_source_json_to_item(source_json: str) -> dict[str, Any]:
	"""
	Map arbitrary source JSON/text into our unified item template using the SAME 2-stage extraction as /crawl:
	- stage=flat: flat fields
	- stage=lots: lotProducts/lotCandidates

	Input is a raw text string (often a JSON blob mixed with other text). We feed it directly to the extractor.
	"""
	src = (source_json or "").strip()
	template = _build_full_item_template()
	if not src:
		return template

	# Meta fields are not part of extract_fields.yaml and cannot be obtained from the crawler's 2-stage extractors.
	# For /normalize_item we extract them from the raw text blob using DeepSeek.
	meta = await _extract_normalize_item_meta_via_llm(src)

	flat_fields = await extract_fields_from_html(src, site_name="normalize_item", stage="flat")
	lots_fields = await extract_fields_from_html(src, site_name="normalize_item", stage="lots")

	merged = dict(template)
	merged.update(flat_fields or {})

	merged["lotProducts"] = (lots_fields or {}).get("lotProducts") or []
	merged["lotCandidates"] = (lots_fields or {}).get("lotCandidates") or []

	# Apply meta as "fill missing" so stage=flat extraction wins when it already provides values.
	for k, v in (meta or {}).items():
		if k in merged and merged.get(k) in ("", None, []):
			merged[k] = v

	return _normalize_item_to_crawler_schema(merged)
