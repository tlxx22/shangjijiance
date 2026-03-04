from __future__ import annotations

import hashlib
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

from .field_schemas import LotCandidates, LotProducts


_NUMBER_LIKE = str | int | float | None
_JSON_SCHEMA_NAME_MAX_LEN = 64
_JSON_SCHEMA_NAME_INVALID_CHARS_RE = re.compile(r"[^A-Za-z0-9_-]")


def _safe_json_schema_name(name: str) -> str:
	"""
	OpenAI-compatible JSON schema name:
	- max length: 64
	- keep to [A-Za-z0-9_-] to be safe across providers
	- deterministic shortening with a short hash suffix
	"""
	base = (name or "").strip()
	base = _JSON_SCHEMA_NAME_INVALID_CHARS_RE.sub("_", base)
	if not base:
		base = "Schema"
	if len(base) <= _JSON_SCHEMA_NAME_MAX_LEN:
		return base

	suffix = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
	keep = _JSON_SCHEMA_NAME_MAX_LEN - 1 - len(suffix)
	if keep <= 0:
		return suffix
	return f"{base[:keep]}_{suffix}"


def build_extract_fields_model(fields: list, *, model_name: str) -> type[BaseModel]:
	"""
	Build a Pydantic model for LangChain `with_structured_output` from our YAML field config.

	Design goals:
	- Keep "number" fields permissive (accept strings like "100万") and let normalize_field_value do conversion.
	- Reuse existing LotProducts/LotCandidates models so lots normalization stays consistent.
	"""
	model_name = _safe_json_schema_name(model_name)
	field_defs: dict[str, tuple[Any, Any]] = {}
	for f in fields:
		key = str(getattr(f, "key", "") or "").strip()
		ftype = str(getattr(f, "type", "") or "").strip()

		if not key:
			continue

		if ftype == "string":
			field_defs[key] = (str, "")
			continue

		if ftype == "number":
			field_defs[key] = (_NUMBER_LIKE, None)
			continue

		if ftype == "boolean":
			# isEquipment: 不确定时默认 true（召回优先）
			field_defs[key] = (bool, True) if key == "isEquipment" else (bool, False)
			continue

		if ftype == "array":
			if key == "lotProducts":
				field_defs[key] = (LotProducts, Field(default_factory=list))
				continue
			if key == "lotCandidates":
				field_defs[key] = (LotCandidates, Field(default_factory=list))
				continue
			field_defs[key] = (list[Any], Field(default_factory=list))
			continue

		# Unknown type: accept anything.
		field_defs[key] = (Any, None)

	return create_model(
		model_name,
		__config__=ConfigDict(extra="ignore"),
		**field_defs,
	)
