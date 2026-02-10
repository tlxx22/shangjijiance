from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from .extract_client import chat_completion
from .config_manager import load_extract_fields, generate_extract_prompt
from .custom_tools import extract_fields_from_html, normalize_field_value
from .field_schemas import LotProducts, LotCandidates, normalize_announcement_type, normalize_estimated_amount


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
_ESTIMATED_AMOUNT_VALUE_RE = re.compile(r"^\d+(?:\.\d+)?(?:~\d+(?:\.\d+)?)?$")


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


async def _extract_normalize_item_meta_flat(src_text: str) -> dict[str, Any]:
	"""
	/normalize_item 专用：一次抽取 meta+flat（使用独立 YAML 配置）。

	字段集合：normalize_item_meta_flat_fields.yaml
	- 在 extract_fields.yaml(flat) 的基础上新增 announcementUrl/announcementName/announcementContent
	- 其余字段定义保持一致（类型/空值规则/枚举等）
	"""
	text = (src_text or "").strip()

	fields_path = "normalize_item_meta_flat_fields.yaml"
	fields = load_extract_fields(fields_path=fields_path, stage="flat")
	extract_prompt = generate_extract_prompt(fields, stage="flat")
	empty_result = {f.key: _TYPE_DEFAULTS.get(f.type, "") for f in fields}

	if not text:
		return empty_result

	system_prompt = f"""
You are an information extraction engine.
You will be given an unstructured text blob from external bid sources (may be JSON, may be key-value text, may be mixed).
Extract the requested fields according to the schema below and return ONLY valid JSON.
No markdown, no code fences, no extra text.

{extract_prompt}

Rules:
- Treat the input as plain text; do not require it to be valid JSON.
- Fill missing fields with the correct empty value by type (string=\"\", number=null, array=[], boolean=false).
- Special rule for estimatedAmount:
  - If announcementType is 招标 or 候选, you MUST output a non-empty amount estimate (yuan) as either \"number\" or \"lo~hi\".
  - The estimate MUST be derived mainly from the procurement items (标的物), quantities, specs, service scope, and similar signals.
    Do NOT use irrelevant fees (e.g. document price, service fee, deposit, CA/platform fees) as the estimate.
  - If announcementType is NOT 招标/候选, you MUST output empty string for estimatedAmount.
- Money amounts are in 单位“元” (convert 万/亿 to 元 if needed).
- Dates are YYYY-MM-DD.
""".strip()

	# Hard cap to avoid extremely large prompts.
	max_chars = 200_000
	if len(text) > max_chars:
		text = text[:max_chars]

	user_prompt = f"SOURCE_TEXT:\\n{text}"
	try:
		output = await asyncio.to_thread(
			chat_completion,
			[
				{"role": "system", "content": system_prompt},
				{"role": "user", "content": user_prompt},
			],
		)
	except Exception:
		return empty_result

	out = _strip_code_fences(output)
	try:
		parsed = json.loads(out)
		if not isinstance(parsed, dict):
			return empty_result
	except Exception:
		return empty_result

	# Normalize by field types using existing normalize_field_value.
	normalized: dict[str, Any] = {}
	for f in fields:
		raw_value = parsed.get(f.key, _TYPE_DEFAULTS.get(f.type, ""))
		normalized[f.key] = normalize_field_value(f.key, raw_value, f.type)
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

	flat_fields = await _extract_normalize_item_meta_flat(src)
	lots_fields = await extract_fields_from_html(src, site_name="normalize_item", stage="lots")

	merged = dict(template)
	merged.update(flat_fields or {})

	merged["lotProducts"] = (lots_fields or {}).get("lotProducts") or []
	merged["lotCandidates"] = (lots_fields or {}).get("lotCandidates") or []

	item = _normalize_item_to_crawler_schema(merged)

	# estimatedAmount：仅当公告类型为【招标/候选】时才保留（由抽取阶段 DeepSeek 结合全文生成）。
	# 本阶段只做：类型 gating + 正则校验（不做任何兜底/推导/再调用）。
	try:
		atype = (item.get("announcementType") or "").strip()
		if atype not in {"招标", "候选"}:
			item["estimatedAmount"] = ""
		else:
			est_text = str(item.get("estimatedAmount") or "").strip()
			normalized = normalize_estimated_amount(est_text) if est_text else ""
			if normalized and not _ESTIMATED_AMOUNT_VALUE_RE.match(normalized):
				normalized = ""
			item["estimatedAmount"] = normalized
	except Exception:
		# normalize_item should be best-effort; failures should not break the whole response.
		pass

	return item
