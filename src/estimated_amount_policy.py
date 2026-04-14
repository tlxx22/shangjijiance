from __future__ import annotations

import re
from typing import Any, MutableMapping


_ESTIMATED_AMOUNT_VALUE_RE = re.compile(r"^\d+(?:\.\d+)?~\d+(?:\.\d+)?$")
_WHITESPACE_RE = re.compile(r"\s+")


def _has_non_empty_value(value: Any) -> bool:
    if value is None:
        return False
    return str(value).strip() != ""


def _is_empty_quantity_for_estimation(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (int, float)) and value == 0:
        return True
    return str(value).strip() in {"", "0"}


def compact_estimated_amount_text(value: Any) -> str:
    if value is None:
        return ""
    return _WHITESPACE_RE.sub("", str(value).strip())


def is_estimated_amount_range_format(value: Any) -> bool:
    text = compact_estimated_amount_text(value)
    return bool(text and _ESTIMATED_AMOUNT_VALUE_RE.fullmatch(text))


def _pick_candidate_amount(lot_candidates: Any) -> Any:
    """
    Pick a fallback amount clue from lotCandidates.

    Priority:
    1) type == "中标"
    2) type == "中标候选人"
    3) first non-empty candidatePrices
    """
    if not isinstance(lot_candidates, list):
        return None

    for preferred_type in ("中标", "中标候选人"):
        for candidate in lot_candidates:
            if not isinstance(candidate, dict):
                continue
            price = candidate.get("candidatePrices")
            if not _has_non_empty_value(price):
                continue
            if str(candidate.get("type") or "").strip() == preferred_type:
                return price

    for candidate in lot_candidates:
        if not isinstance(candidate, dict):
            continue
        price = candidate.get("candidatePrices")
        if _has_non_empty_value(price):
            return price

    return None


def pick_estimated_amount_priority_clue(item: MutableMapping[str, Any]) -> Any:
    winner_amount = item.get("winnerAmount")
    if _has_non_empty_value(winner_amount):
        return winner_amount
    return _pick_candidate_amount(item.get("lotCandidates") or [])


def pick_estimated_amount_budget_clue(item: MutableMapping[str, Any]) -> Any:
    budget_amount = item.get("budgetAmount")
    if _has_non_empty_value(budget_amount):
        return budget_amount
    return None


def is_effective_lot_for_estimation(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False

    subjects = entry.get("subjects")
    quantities = entry.get("quantities")
    models = entry.get("models")

    if _has_non_empty_value(subjects) and (
        _is_empty_quantity_for_estimation(quantities) or not _has_non_empty_value(models)
    ):
        return False
    return True


def build_effective_lot_products_for_estimation(lot_products: Any) -> list[dict[str, Any]]:
    rows = list(lot_products or []) if isinstance(lot_products, list) else []
    return [entry for entry in rows if is_effective_lot_for_estimation(entry)]


def apply_estimated_amount_policy(item: MutableMapping[str, Any]) -> None:
    """
    Lightweight guard for estimatedAmount.

    The dedicated estimated_amount LLM stage owns the semantics and formatting.
    This helper only keeps the field empty when there is no structured clue at all.
    """
    try:
        if pick_estimated_amount_priority_clue(item) is not None:
            return
        if pick_estimated_amount_budget_clue(item) is not None:
            return
        if build_effective_lot_products_for_estimation(item.get("lotProducts") or []):
            return
        item["estimatedAmount"] = ""
    except Exception:
        return
