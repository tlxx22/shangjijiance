from __future__ import annotations

import asyncio
import re
from typing import Any

from pydantic import BaseModel, Field

from .concrete_product_table import (
    format_concrete_product_table_for_prompt,
    get_effective_concrete_product_terms_set,
)
from .deepseek_langchain import ainvoke_structured
from .logger_config import get_logger

logger = get_logger()

_PRODUCT_CATEGORY_MAX_RETRIES = 1
_PRODUCT_CATEGORY_LLM_SEMAPHORE = asyncio.Semaphore(4)
_PRODUCT_CATEGORY_MULTI_VALUE_RE = re.compile(r"[\u3001,\uff0c;\uff1b\n\r]|(?:\s/\s)")
_PRODUCT_CATEGORY_MULTI_VALUE_SPLIT_RE = re.compile(r"(?:\s/\s)|[\u3001,\uff0c;\uff1b\n\r]+")

_PRODUCT_CATEGORY_SYSTEM_PROMPT = """
You are a strict concrete product classifier for Chinese procurement items.

Task:
- Read the single `subjects` string.
- Choose `productCategory` from the provided candidate table.

Hard rules:
- Use ONLY `subjects`. Do NOT use models, title, body, lotName, lotNumber, or any other field.
- The final answer must be EXACTLY one candidate term from the candidate table.
- If no candidate is meaningfully supported by `subjects`, output an empty string.
- If several candidates seem related or similar, you MUST still choose the single most suitable / closest / best-matching candidate.
- Do NOT return an empty string just because several candidates look plausible.
- Never return a whole row, multiple candidates, a punctuation-joined list, or any explanation.
- All candidates are peer candidates. Line breaks are only for readability and do not imply priority.
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
	attempt: int,
	previous_value: str,
	previous_reason: str,
) -> str:
	user_prompt = (
		f"subjects:\n{subjects}\n\n"
		f"candidate_table:\n{prompt_table}\n"
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
				"Do NOT return multiple candidates.\n"
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
	candidate_terms = get_effective_concrete_product_terms_set(product_category_table)
	prompt_table = format_concrete_product_table_for_prompt(product_category_table)
	processed: list[dict[str, Any]] = []

	for index, row in enumerate(rows):
		if not isinstance(row, dict):
			processed.append(row)
			continue

		subjects = (row.get("subjects") or "").strip()
		last_value = ""
		last_reason = "not_attempted"

		for attempt in range(1, max_retries + 1):
			try:
				generated_value = await _generate_product_category_once(
					subjects=subjects,
					prompt_table=prompt_table,
					candidate_terms=candidate_terms,
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
