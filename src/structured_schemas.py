from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

from .field_schemas import LotCandidates, LotProducts


_NUMBER_LIKE = str | int | float | None


def build_extract_fields_model(fields: list, *, model_name: str) -> type[BaseModel]:
	"""
	Build a Pydantic model for LangChain `with_structured_output` from our YAML field config.

	Design goals:
	- Keep "number" fields permissive (accept strings like "100万") and let normalize_field_value do conversion.
	- Reuse existing LotProducts/LotCandidates models so lots normalization stays consistent.
	"""
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
			field_defs[key] = (bool, False)
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

