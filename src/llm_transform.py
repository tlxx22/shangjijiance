from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from .extract_client import chat_completion
from .config_manager import load_extract_fields, generate_extract_prompt
from .custom_tools import normalize_field_value
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
	Map arbitrary source JSON text into our unified item template using DeepSeek.
	Routing is controlled by trans.ROUTE via extract_client.chat_completion.
	"""
	src = (source_json or "").strip()
	if not src:
		return _build_full_item_template()

	template = _build_full_item_template()
	keys = [k for k in template.keys() if k != "dataId"]  # computed by server

	# Reuse existing extraction prompts so field definitions stay identical to crawler.
	flat_prompt = generate_extract_prompt(load_extract_fields(stage="flat"), stage="flat")
	lots_prompt = generate_extract_prompt(load_extract_fields(stage="lots"), stage="lots")

	system_prompt = f"""
You are a normalization engine.
You will be given a JSON string from external sources (3rd-party API / Excel import / other crawlers).
Extract and map fields into our TARGET JSON template and return ONLY valid JSON.

Important:
- The output must be a single JSON object with EXACTLY these keys:
  {", ".join(keys)}
- Do NOT output any extra keys.
- Fill missing values with correct empty defaults:
  - string: ""
  - number: null
  - array: []
- Dates must be YYYY-MM-DD when possible.
- Money amounts for budgetAmount must be in 万元 (number). If unknown, use null.
- lotProducts and lotCandidates must follow EXACTLY the crawler schema (do NOT invent fields like "description").
- lotNumber must be 标段一/标段二/...; if not specified but lot object is needed, use 标段一.
- Do not invent information not present in the input JSON string.

Field definitions (MUST follow these exactly):
{flat_prompt}

{lots_prompt}
""".strip()

	user_prompt = f"SOURCE_JSON_TEXT:\\n{src}"
	out = await asyncio.to_thread(
		chat_completion,
		[
			{"role": "system", "content": system_prompt},
			{"role": "user", "content": user_prompt},
		],
	)
	out = _strip_code_fences(out)

	try:
		parsed = json.loads(out)
		if not isinstance(parsed, dict):
			return template
	except Exception:
		return template

	# Merge to template then normalize to the same schema as crawler output.
	merged = dict(template)
	for k in keys:
		if k in parsed:
			merged[k] = parsed[k]

	return _normalize_item_to_crawler_schema(merged)
