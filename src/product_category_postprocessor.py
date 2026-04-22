from __future__ import annotations

import asyncio
import re
from typing import Any

from pydantic import BaseModel, Field

from .concrete_product_table import (
    format_concrete_product_table_for_prompt,
    get_effective_concrete_product_terms,
    get_effective_concrete_product_terms_set,
)
from .deepseek_langchain import ainvoke_structured
from .logger_config import get_logger

logger = get_logger()

_PRODUCT_CATEGORY_MAX_RETRIES = 1
_PRODUCT_CATEGORY_LLM_SEMAPHORE = asyncio.Semaphore(4)
_PRODUCT_CATEGORY_MULTI_VALUE_RE = re.compile(r"[\u3001,\uff0c;\uff1b\n\r]|(?:\s/\s)")
_PRODUCT_CATEGORY_MULTI_VALUE_SPLIT_RE = re.compile(r"(?:\s/\s)|[\u3001,\uff0c;\uff1b\n\r]+")
_PRODUCT_CATEGORY_WHITESPACE_RE = re.compile(r"\s+")
_PRODUCT_CATEGORY_BUNDLED_PAREN_RE = re.compile(r"[（(][^）)]*(?:含|带|配)[^）)]*[）)]")
_PRODUCT_CATEGORY_BUNDLED_TAIL_RE = re.compile(
    r"(?:及附属设备|及配套设备|及附属设施|及附件|及随机附件|及备品备件|含附件|含随机附件|含备品备件)\s*$"
)
_PRODUCT_CATEGORY_TRAILING_PUNCT_RE = re.compile(r"[\s,，;；、:：]+$")

_PRODUCT_CATEGORY_SYSTEM_PROMPT = """
You are a strict concrete product classifier for Chinese procurement items.

Task:
- Read the single `subjects` string.
- Choose `productCategory` from the provided candidate table.

Hard rules:
- Use ONLY `subjects`. Do NOT use models, title, body, lotName, lotNumber, or any other field.
- If `subjects` exactly matches a candidate term, you MUST return that exact candidate term.
- If an exact match exists, do NOT replace it with a broader term, related term, sibling term, parent category, or another term from the same row.
- The final answer must be EXACTLY one candidate term from the candidate table.
- If no candidate is meaningfully supported by `subjects`, output an empty string.
- If several candidates seem related or similar, you MUST still choose the single most suitable / closest / best-matching candidate.
- Do NOT return an empty string just because several candidates look plausible.
- 优先保持主类一致，再比较修饰词。 First keep the main product class consistent, then compare subtype modifiers.
- If `subjects` clearly contains a main class term (for example 消防车 / 履带起重机 / 叉车 / 挖掘机), prefer candidates that keep that same main class first.
- Do NOT jump to another main class just because one modifier word overlaps more strongly.
- If `subjects` first names a whole machine / complete equipment target and then appends bundled-scope wording such as `含...`, `带...`, `配...`, `及附属设备`, `及配套设备`, `及附属设施`, `含附件`, `含备品备件`, treat the leading whole-machine term as the main procurement object.
- Such bundled-scope wording does NOT by itself make the target a part/accessory-only item, and should NOT by itself force an empty string.
- In these cases, classify by the main whole-machine noun phrase before the bundled wording, rather than by the bundled accessories themselves.
- Example: if `subjects` is `风力发电机组（含塔筒及法兰）及附属设备`, it still indicates a whole-machine wind-turbine-generator-set target and should map to the best-supported whole-machine candidate instead of returning empty solely because of `含塔筒及法兰` or `及附属设备`.
- Do NOT invent unsupported subtype qualifiers. If the bundled wording does not specify a subtype such as `陆上` / `海上` / `低风速`, do not fabricate that qualifier; choose the closest supported whole-machine candidate from the table.
- Strong examples for bundled-scope wording:
  - If `subjects` is `风力发电机组（含塔筒及法兰）及附属设备` and the candidate table contains `风力发电机组`, return `风力发电机组`.
  - If `subjects` is `风力发电机组（含塔筒及法兰）及附属设备` and the table does NOT contain `风力发电机组` but does contain a closest whole-machine candidate such as `风力发电机`, return that closest whole-machine candidate rather than an empty string.
  - Returning an empty string for the above kind of bundled whole-machine wording is WRONG unless the table truly has no meaningfully supported whole-machine candidate at all.
- If `subjects` is clearly NOT a whole machine / complete equipment target, prefer empty string rather than forcing a machine category.
- Non-whole-machine examples include but are not limited to 系统、配件、备件、零件、组件、附件、脚踏板、踏板、护栏、支架、底座、仪表、控制器、模块、总成、管路、电缆、接头、阀、泵头、滤芯、修理包.
- When `subjects` names a part, accessory, attachment, module, or system of a machine rather than the machine itself, do NOT map it to a whole-machine category.
- Never mechanically choose the first term in a row just because the row looks relevant.
- Never return a whole row, multiple candidates, a punctuation-joined list, or any explanation.
- All candidates are peer candidates. Line breaks are only for readability and do not imply priority.
- Example: if `subjects` is `电动单梁起重机` and that exact candidate exists, you MUST return `电动单梁起重机`, not `门式回转起重机` or another nearby crane term.
- Return ONLY valid JSON matching schema: {"productCategory": "..."}.
""".strip()


class ProductCategorySelection(BaseModel):
	productCategory: str = Field(default="")


def _truncate_for_log(text: str, max_chars: int = 80) -> str:
	s = (text or "").strip()
	if len(s) <= max_chars:
		return s
	return f"{s[:max_chars]}..."


def _looks_like_multi_value_output(value: str) -> bool:
	return bool(_PRODUCT_CATEGORY_MULTI_VALUE_RE.search((value or "").strip()))


def _normalize_exact_match_text(value: str) -> str:
	return _PRODUCT_CATEGORY_WHITESPACE_RE.sub(" ", (value or "").strip())


def _derive_main_subject_hint(subjects: str) -> str:
	text = (subjects or "").strip()
	if not text:
		return ""

	text = _PRODUCT_CATEGORY_BUNDLED_PAREN_RE.sub("", text)
	text = _PRODUCT_CATEGORY_BUNDLED_TAIL_RE.sub("", text)
	text = _PRODUCT_CATEGORY_TRAILING_PUNCT_RE.sub("", text).strip()
	return text


def _find_closest_candidate_hint(
	subjects: str,
	*,
	candidate_terms: list[str],
) -> str:
	text = _normalize_exact_match_text(subjects)
	if not text:
		return ""

	for term in sorted(candidate_terms, key=len, reverse=True):
		candidate = _normalize_exact_match_text(term)
		if candidate and candidate in text:
			return term.strip()
	return ""


def _find_exact_product_category_match(
	subjects: str,
	*,
	candidate_terms: list[str],
) -> str:
	normalized_subjects = _normalize_exact_match_text(subjects)
	if not normalized_subjects:
		return ""

	for term in candidate_terms:
		candidate = (term or "").strip()
		if not candidate:
			continue
		if _normalize_exact_match_text(candidate) == normalized_subjects:
			return candidate
	return ""


def _extract_candidates_from_previous_multi_value(
	value: str,
	*,
	candidate_terms: set[str],
) -> list[str]:
	candidates: list[str] = []
	seen: set[str] = set()
	for part in _PRODUCT_CATEGORY_MULTI_VALUE_SPLIT_RE.split((value or "").strip()):
		text = part.strip().strip("'\"")
		if not text or text not in candidate_terms or text in seen:
			continue
		seen.add(text)
		candidates.append(text)
	return candidates


def _pick_first_value_from_multi_value_output(value: str) -> str:
	for part in _PRODUCT_CATEGORY_MULTI_VALUE_SPLIT_RE.split((value or "").strip()):
		text = part.strip().strip("'\"")
		if text:
			return text
	return (value or "").strip()


def validate_product_category_output(
	value: str,
	*,
	candidate_terms: set[str],
) -> tuple[bool, str]:
	text = (value or "").strip()
	if text == "":
		return True, "no_match"
	if text in candidate_terms:
		return True, "exact_match"
	if _looks_like_multi_value_output(text):
		return False, "multi_value"
	return False, "not_in_table"


async def _generate_product_category_once(
	*,
	subjects: str,
	prompt_table: str,
	candidate_terms: set[str],
	main_subject_hint: str,
	closest_candidate_hint: str,
	attempt: int,
	previous_value: str,
	previous_reason: str,
) -> str:
	user_prompt = (
		f"subjects:\n{subjects}\n\n"
		f"candidate_table:\n{prompt_table}\n"
	)
	if main_subject_hint:
		user_prompt += (
			f"\nmechanical_main_subject_hint:\n{main_subject_hint}\n"
			"This hint is derived mechanically from `subjects` by trimming bundled-scope wording only.\n"
		)
	if closest_candidate_hint:
		user_prompt += (
			f"\nmechanical_closest_candidate_hint:\n{closest_candidate_hint}\n"
			"This hint is derived mechanically from `subjects` and the candidate table only.\n"
			"If it is consistent with `subjects`, prefer it over returning an empty string.\n"
		)
	if attempt > 1:
		if previous_reason == "multi_value":
			previous_candidates = _extract_candidates_from_previous_multi_value(
				previous_value,
				candidate_terms=candidate_terms,
			)
			user_prompt += (
				f"\nPrevious invalid output: {previous_value!r}\n"
				"Failure reason: multi_value (you returned multiple candidates).\n"
				"Correct it by choosing exactly ONE most suitable candidate.\n"
				"If `subjects` exactly matches one candidate term, return that exact term.\n"
				"Do NOT return multiple candidates.\n"
				"Do NOT mechanically choose the first term from a relevant row.\n"
				"Do NOT return an empty string just because several candidates look similar.\n"
				"Compare them and pick the single best match for `subjects`.\n"
			)
			if previous_candidates:
				user_prompt += "Candidates extracted from your previous invalid output:\n"
				for candidate in previous_candidates:
					user_prompt += f"- {candidate}\n"
				user_prompt += (
					"Your corrected answer should preferably be chosen from the candidates listed above.\n"
				)
		else:
			user_prompt += (
				f"\nPrevious invalid output: {previous_value!r}\n"
				f"Failure reason: {previous_reason}\n"
				"If `subjects` exactly matches one candidate term, return that exact term.\n"
				"Correct the answer. Return exactly one candidate term or an empty string.\n"
			)

	async with _PRODUCT_CATEGORY_LLM_SEMAPHORE:
		result = await ainvoke_structured(
			[
				{"role": "system", "content": _PRODUCT_CATEGORY_SYSTEM_PROMPT},
				{"role": "user", "content": user_prompt},
			],
			ProductCategorySelection,
		)
	return (result.productCategory or "").strip()


async def fill_product_categories_after_lots(
	lot_products: list[dict[str, Any]] | None,
	*,
	site_name: str,
	product_category_table: str | None = None,
	max_retries: int = _PRODUCT_CATEGORY_MAX_RETRIES,
) -> list[dict[str, Any]]:
	rows = list(lot_products or [])
	if not rows:
		return rows

	max_retries = max(1, int(max_retries))
	candidate_terms_ordered = get_effective_concrete_product_terms(product_category_table)
	candidate_terms = set(candidate_terms_ordered) or get_effective_concrete_product_terms_set(product_category_table)
	prompt_table = format_concrete_product_table_for_prompt(product_category_table)
	processed: list[dict[str, Any]] = []

	for index, row in enumerate(rows):
		if not isinstance(row, dict):
			processed.append(row)
			continue

		subjects = (row.get("subjects") or "").strip()
		main_subject_hint = _derive_main_subject_hint(subjects)
		closest_candidate_hint = _find_closest_candidate_hint(
			main_subject_hint or subjects,
			candidate_terms=candidate_terms_ordered,
		)
		exact_match = _find_exact_product_category_match(
			subjects,
			candidate_terms=candidate_terms_ordered,
		)
		if exact_match:
			new_row = dict(row)
			new_row["productCategory"] = exact_match
			logger.info(
				f"[{site_name}] lotProducts[{index}] productCategory exact-match "
				f"subjects={_truncate_for_log(subjects)!r} output={exact_match!r}"
			)
			processed.append(new_row)
			continue

		last_value = ""
		last_reason = "not_attempted"

		for attempt in range(1, max_retries + 1):
			try:
				generated_value = await _generate_product_category_once(
					subjects=subjects,
					prompt_table=prompt_table,
					candidate_terms=candidate_terms,
					main_subject_hint=main_subject_hint,
					closest_candidate_hint=closest_candidate_hint,
					attempt=attempt,
					previous_value=last_value,
					previous_reason=last_reason,
				)
			except Exception as e:
				last_value = ""
				last_reason = f"llm_error:{e}"
				logger.warning(
					f"[{site_name}] lotProducts[{index}] productCategory generation failed "
					f"attempt {attempt}/{max_retries} subjects={_truncate_for_log(subjects)!r}: {e}"
				)
				continue

			last_value = (generated_value or "").strip()
			ok, reason = validate_product_category_output(
				last_value,
				candidate_terms=candidate_terms,
			)
			last_reason = reason
			logger.info(
				f"[{site_name}] lotProducts[{index}] productCategory attempt {attempt}/{max_retries} "
				f"subjects={_truncate_for_log(subjects)!r} output={last_value!r} validation={reason}"
			)
			if ok:
				break

		new_row = dict(row)
		if last_reason == "multi_value":
			fallback_value = _pick_first_value_from_multi_value_output(last_value)
			logger.info(
				f"[{site_name}] lotProducts[{index}] productCategory max-retries fallback "
				f"subjects={_truncate_for_log(subjects)!r} raw_output={last_value!r} "
				f"fallback_output={fallback_value!r}"
			)
			last_value = fallback_value
			last_reason = "max_retries_first_value"
		new_row["productCategory"] = last_value
		logger.info(
			f"[{site_name}] lotProducts[{index}] productCategory final "
			f"subjects={_truncate_for_log(subjects)!r} output={last_value!r} reason={last_reason}"
		)
		processed.append(new_row)

	return processed
