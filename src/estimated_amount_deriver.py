from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, MutableMapping

from .estimated_amount_policy import (
    apply_estimated_amount_policy,
    build_effective_lot_products_for_estimation,
    is_estimated_amount_range_format,
    pick_estimated_amount_budget_clue,
    pick_estimated_amount_priority_clue,
)
from .extract_client import chat_completion
from .logger_config import get_logger

logger = get_logger()


Extractor = Callable[..., Awaitable[dict[str, Any] | str]]
MAX_ESTIMATED_AMOUNT_RETRIES = 5

_ESTIMATED_AMOUNT_SYSTEM_PROMPT = """
You are an estimated-amount string generator, not a JSON extractor.
Your entire response must be plain text and can only be one of the following:
1) `A~B`
2) empty string

A and B must be Arabic numerals and may contain decimal points. Do not output any other characters.
Do not output JSON, Markdown, code fences, field names, explanations, units, spaces, commas, currency symbols, prefixes, or suffixes.

Rules:
- If the input already contains an explicit awarded / winning / transaction / candidate bid amount clue, use it first. If only one exact amount is known, output `X~X`.
- Otherwise, if the input contains an explicit project-level total budget / procurement budget / overall budget clue, use that total amount for the whole notice. If only one exact amount is known, output `X~X`.
- If one notice contains both a project-level total budget and several package / lot budgets, the project-level total budget has higher priority for the final whole-notice estimatedAmount. Do NOT convert sibling package budgets into `min~max` in that situation.
- If there is no project-level total budget but there are several package / lot budgets, estimate the whole-notice amount from the combined package scope. Do NOT use sibling package budgets as lower bound vs upper bound of one range.
- If lotProducts exists, do not return empty. Even without explicit budget or unit price, you must estimate a reasonable, conservative, and fairly wide total project range based on the procurement items.
- This rule does NOT depend on whether the notice is an equipment purchase. Even if the extracted scope is repair, maintenance, installation, transport, engineering service, or any other service-type subject, you must still estimate the total transaction/service amount range for the extracted scope instead of returning empty.
- If there are multiple procurement lines and some quantities are missing, you must still estimate for the whole package instead of returning empty.
- Zero values, blanks, and placeholders inside lotProducts are not valid lower bounds.
- Only use hard money bounds from the body, such as budget cap, maximum price, control price, reserve price, starting bid, or minimum price. Ignore contacts, phones, dates, rankings, procedures, and unrelated fees.
- Ignore non-money ranges such as model ranges, date ranges, or `1.4~3m3`.
- Bare `~`, `100000~`, `~120000`, or any output with an empty left/right bound is always invalid.

Invalid examples: `about 100k`, `10-12?`, `100000 ~ 120000`, `RMB100000~120000`, `estimatedAmount:100000~120000`, `~`, `100000~`, `~120000`, `0~0`, `1~1` unless the input explicitly states that exact real amount.
Valid examples: `100000~120000`, `350000~350000`
""".strip()


def _text_or_empty(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _extract_estimated_amount_candidate_output(response: dict[str, Any] | str | None) -> str:
    if isinstance(response, dict):
        return _text_or_empty(response.get("estimatedAmount"))
    return _text_or_empty(response)


async def _generate_estimated_amount_text(
    text: str,
    *,
    site_name: str,
    stage: str,
    fields_path: str,
    product_category_table: str | None = None,
) -> dict[str, Any]:
    del stage, fields_path, product_category_table

    raw = await asyncio.to_thread(
        chat_completion,
        [
            {"role": "system", "content": _ESTIMATED_AMOUNT_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    )
    output = _text_or_empty(raw)
    logger.info(f"[{site_name}] estimated_amount 生成完成")
    return {"estimatedAmount": output}


def build_estimated_amount_source_text(
    *,
    lot_products: list[dict],
    announcement_content: str,
    priority_amount: Any = None,
    budget_amount: Any = None,
    current_estimated_amount: Any = None,
    previous_invalid_output: str = "",
    excerpt_len: int = 12000,
) -> str:
    lot_products_json = json.dumps(lot_products or [], ensure_ascii=False)
    body_excerpt = str(announcement_content or "").strip()[: max(0, int(excerpt_len or 0))]

    clue_payload: dict[str, Any] = {}
    if _text_or_empty(priority_amount):
        clue_payload["priorityAmountClue"] = priority_amount
    if _text_or_empty(budget_amount):
        clue_payload["budgetAmountClue"] = budget_amount
    if _text_or_empty(current_estimated_amount):
        clue_payload["currentEstimatedAmount"] = _text_or_empty(current_estimated_amount)

    parts: list[str] = []
    if clue_payload:
        parts.append("Priority amount clues (JSON): " + json.dumps(clue_payload, ensure_ascii=False))

    parts.append("Procurement items (lotProducts JSON): " + lot_products_json)

    if body_excerpt:
        parts.append(
            "Body excerpt (ONLY for hard money bounds such as budget cap, maximum price, control price, reserve price, minimum price, or starting bid; "
            "do NOT reconstruct procurement items from the body): " + body_excerpt
        )

    if _text_or_empty(previous_invalid_output):
        parts.append(
            "Previous estimatedAmount output was invalid: "
            + _text_or_empty(previous_invalid_output)
            + ". Retry now and output ONLY one valid numeric range string A~B. "
              "Do NOT output spaces, units, commas, currency symbols, Chinese words, prefixes, suffixes, or any explanation."
        )

    parts.append(
        "Notes: lotProducts is the only source of item identity, quantity, model, and scope. "
        "Do NOT reconstruct or rewrite procurement items from the body. "
        "If the input already contains an explicit winning / awarded / candidate bid amount clue, use it first; if only one amount is known, output X~X. "
        "Otherwise, if the input contains a project-level total budget clue, use that total amount for the whole notice; if only one amount is known, output X~X. "
        "If both a project total budget and package budgets are present, the project total budget wins. Never turn package budgets into a min~max range when a total budget already exists. "
        "If only multiple package budgets exist, reason about the whole notice from the combined package scope instead of using sibling package budgets as the two ends of one range. "
        "If there are procurement items but no explicit amount, estimate a realistic total range from real-world market prices for the same or highly similar items. "
        "Even if the extracted scope is repair, maintenance, installation, transport, or construction/service scope, you must still estimate the total transaction/service amount range for the extracted scope instead of returning empty. "
        "If there are multiple procurement lines and some quantities are missing, you must still estimate a conservative total package range instead of returning empty. "
        "Treat zero unit price / quantity / total values in lotProducts as unknown placeholders, not as a valid lower bound. "
        "Ignore non-money ranges such as 1.4~3m3, dates, phone numbers, rankings, and unrelated fees. "
        "The final output is valid only when estimatedAmount is a numeric range A~B with no spaces. Outputs like ~, 100000~, ~120000, 0~0, or 1~1 are invalid placeholders unless the input explicitly states that exact real amount."
    )
    return "\n\n".join(parts).strip()


async def fill_estimated_amount_after_lots(
    item: MutableMapping[str, Any],
    *,
    site_name: str,
    fields_path: str,
    extractor: Extractor | None = None,
) -> None:
    """
    Derive estimatedAmount after lotProducts / lotCandidates are finalized.

    Rules:
    1) Do not normalize or rewrite the model output.
    2) Only validate whether the output matches A~B after removing spaces.
    3) If invalid, retry the dedicated estimated_amount generation up to 5 times.
    4) If all retries still fail, fall back to the first raw output.
    """
    try:
        apply_estimated_amount_policy(item)
    except Exception:
        return

    current_output = item.get("estimatedAmount")
    if is_estimated_amount_range_format(current_output):
        return

    raw_lot_products = [entry for entry in (item.get("lotProducts") or []) if isinstance(entry, dict)]
    lot_products = build_effective_lot_products_for_estimation(raw_lot_products)
    priority_amount = pick_estimated_amount_priority_clue(item)
    budget_amount = pick_estimated_amount_budget_clue(item)

    filtered_count = max(0, len(raw_lot_products) - len(lot_products))
    if filtered_count:
        logger.info(
            f"[{site_name}] estimatedAmount lot filter: raw={len(raw_lot_products)} effective={len(lot_products)} "
            f"filtered={filtered_count} reason=subjects-only lot excluded from estimation"
        )

    if priority_amount is None and budget_amount is None and not lot_products:
        item["estimatedAmount"] = ""
        return

    if extractor is None:
        extractor = _generate_estimated_amount_text

    original_output = _text_or_empty(current_output)
    first_raw_output: str | None = None
    previous_invalid_output = original_output

    for attempt in range(1, MAX_ESTIMATED_AMOUNT_RETRIES + 1):
        try:
            text = build_estimated_amount_source_text(
                lot_products=lot_products,
                announcement_content=str(item.get("announcementContent") or ""),
                priority_amount=priority_amount,
                budget_amount=budget_amount,
                current_estimated_amount=original_output,
                previous_invalid_output=previous_invalid_output if attempt > 1 else "",
            )
            out = await extractor(
                text,
                site_name=site_name,
                stage="estimated_amount",
                fields_path=fields_path,
                product_category_table=None,
            )
            candidate_output = _extract_estimated_amount_candidate_output(out)
        except Exception as exc:
            logger.warning(f"[{site_name}] estimatedAmount attempt {attempt} failed: {exc}")
            candidate_output = ""

        candidate_text = _text_or_empty(candidate_output)
        item["estimatedAmount"] = candidate_text
        if first_raw_output is None:
            first_raw_output = candidate_text

        if is_estimated_amount_range_format(candidate_text):
            return

        if candidate_text:
            previous_invalid_output = candidate_text

    item["estimatedAmount"] = first_raw_output if first_raw_output is not None else original_output


