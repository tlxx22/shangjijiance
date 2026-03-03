from __future__ import annotations

import re
from typing import Any, MutableMapping

from .field_schemas import normalize_estimated_amount


_ESTIMATED_AMOUNT_VALUE_RE = re.compile(r"^\d+(?:\.\d+)?~\d+(?:\.\d+)?$")


def _pick_candidate_amount(lot_candidates: Any) -> Any:
	"""
	Pick a fallback amount from lotCandidates for estimatedAmount.

	Priority:
	1) type == "中标"
	2) type == "中标候选人"
	3) first non-empty candidatePrices
	"""
	if not isinstance(lot_candidates, list):
		return None

	# Prefer type="中标"
	for c in lot_candidates:
		if not isinstance(c, dict):
			continue
		price = c.get("candidatePrices")
		if price is None:
			continue
		if str(c.get("type") or "").strip() == "中标":
			return price

	# Then type="中标候选人"
	for c in lot_candidates:
		if not isinstance(c, dict):
			continue
		price = c.get("candidatePrices")
		if price is None:
			continue
		if str(c.get("type") or "").strip() == "中标候选人":
			return price

	# Finally, any non-empty price
	for c in lot_candidates:
		if not isinstance(c, dict):
			continue
		price = c.get("candidatePrices")
		if price is None:
			continue
		return price

	return None


def apply_estimated_amount_policy(item: MutableMapping[str, Any]) -> None:
	"""
	Best-effort post-processing for estimatedAmount.

	Rules:
	1) If winnerAmount exists -> estimatedAmount = winnerAmount as "x~x"
	2) Else if lotCandidates has a usable price -> estimatedAmount = that price as "x~x"
	3) Else if no lotProducts -> estimatedAmount = ""
	4) Else keep AI estimate, but it MUST match "lo~hi" (otherwise "")
	"""
	try:
		winner_amount = item.get("winnerAmount")
		candidate_amount = None if winner_amount is not None else _pick_candidate_amount(item.get("lotCandidates") or [])

		chosen_amount = winner_amount if winner_amount is not None else candidate_amount
		if chosen_amount is not None:
			normalized = normalize_estimated_amount(chosen_amount)
			item["estimatedAmount"] = normalized if normalized and _ESTIMATED_AMOUNT_VALUE_RE.match(normalized) else ""
			return

		# Only keep AI estimate when procurement items exist.
		if not (item.get("lotProducts") or []):
			item["estimatedAmount"] = ""
			return

		est_text = str(item.get("estimatedAmount") or "").strip()
		normalized = normalize_estimated_amount(est_text) if est_text else ""
		if normalized and not _ESTIMATED_AMOUNT_VALUE_RE.match(normalized):
			normalized = ""
		item["estimatedAmount"] = normalized
	except Exception:
		# Must never break upstream flows.
		return
