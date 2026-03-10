from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, MutableMapping

from .estimated_amount_policy import (
    apply_estimated_amount_policy,
    is_estimated_amount_range_format,
    pick_estimated_amount_priority_clue,
)
from .logger_config import get_logger

logger = get_logger()


Extractor = Callable[..., Awaitable[dict[str, Any]]]
MAX_ESTIMATED_AMOUNT_RETRIES = 5


def _text_or_empty(value: Any) -> str:
    return "" if value is None else str(value).strip()


def build_estimated_amount_source_text(
    *,
    lot_products: list[dict],
    announcement_content: str,
    priority_amount: Any = None,
    current_estimated_amount: Any = None,
    previous_invalid_output: str = "",
    excerpt_len: int = 12000,
) -> str:
    lot_products_json = json.dumps(lot_products or [], ensure_ascii=False)
    body_excerpt = str(announcement_content or "").strip()[: max(0, int(excerpt_len or 0))]

    clue_payload: dict[str, Any] = {}
    if _text_or_empty(priority_amount):
        clue_payload["priorityAmountClue"] = priority_amount
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
        "If there are procurement items but no explicit amount, estimate a realistic total range from real-world market prices for the same or highly similar items. "
        "Treat zero unit price / quantity / total values in lotProducts as unknown placeholders, not as a valid lower bound. "
        "Ignore non-money ranges such as 1.4~3m3, dates, phone numbers, rankings, and unrelated fees. "
        "The final output is valid only when estimatedAmount is a numeric range A~B."
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
    1) Do not normalize or coerce the model output into another amount.
    2) Only validate whether the output matches A~B after removing spaces.
    3) If invalid, retry the dedicated estimated_amount stage up to 5 times.
    4) If all retries still fail, fall back to the first raw model output.
    """
    try:
        apply_estimated_amount_policy(item)
    except Exception:
        return

    current_output = item.get("estimatedAmount")
    if is_estimated_amount_range_format(current_output):
        return

    lot_products = [entry for entry in (item.get("lotProducts") or []) if isinstance(entry, dict)]
    priority_amount = pick_estimated_amount_priority_clue(item)
    if priority_amount is None and not lot_products:
        return

    if extractor is None:
        try:
            from .custom_tools import extract_fields_from_text as extractor  # local import to avoid cycles
        except Exception as exc:
            logger.warning(f"[{site_name}] estimatedAmount init failed while importing extractor: {exc}")
            return

    original_output = _text_or_empty(current_output)
    first_raw_output: str | None = None
    previous_invalid_output = original_output

    for attempt in range(1, MAX_ESTIMATED_AMOUNT_RETRIES + 1):
        try:
            text = build_estimated_amount_source_text(
                lot_products=lot_products,
                announcement_content=str(item.get("announcementContent") or ""),
                priority_amount=priority_amount,
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
            candidate_output = out.get("estimatedAmount") if isinstance(out, dict) else item.get("estimatedAmount")
        except Exception as exc:
            logger.warning(f"[{site_name}] estimatedAmount LLM attempt {attempt} failed: {exc}")
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
