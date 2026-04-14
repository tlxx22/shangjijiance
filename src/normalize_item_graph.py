from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .address_normalizer import extract_admin_divisions_from_details
from .announcement_type_repair import AnnouncementTypeRepairError, repair_announcement_type
from .custom_tools import (
	_INPUT_TRUNCATED_META_KEY,
	compute_data_id,
	extract_project_name_from_title_text,
	_extract_normalize_item_title_section,
	_prepare_normalize_item_source_json_with_cleaned_body,
)
from .estimated_amount_deriver import fill_estimated_amount_after_lots
from .field_schemas import ANNOUNCEMENT_TYPES
from .llm_transform import (
	_build_full_item_template,
	_extract_normalize_item_fields,
	_normalize_item_to_crawler_schema,
)
from .logger_config import get_logger
from .product_category_postprocessor import fill_product_categories_after_lots

logger = get_logger()

_FIELDS_PATH = "normalize_item_meta_flat_fields.yaml"
_SITE_NAME = "normalize_item"


class NormalizeItemGraphState(TypedDict, total=False):
	source_json: str
	llm_source_json: str
	product_category_table: str | None
	template: dict[str, Any]
	direct_announcement_name: str
	cleaned_announcement_content: str
	title_project_name: str
	meta_fields: dict[str, Any]
	meta_input_truncated: bool
	contacts_fields: dict[str, Any]
	contacts_input_truncated: bool
	address_detail_fields: dict[str, Any]
	address_detail_input_truncated: bool
	lots_fields: dict[str, Any]
	lots_input_truncated: bool
	merged_item: dict[str, Any]
	item: dict[str, Any]
	raw_announcement_type: str
	address_fields: dict[str, Any]
	data_id: str


def _prepare_input(state: NormalizeItemGraphState) -> NormalizeItemGraphState:
	source_json = (state.get("source_json") or "").strip()
	direct_announcement_name = _extract_normalize_item_title_section(source_json)
	cleaned_announcement_content, llm_source_json = _prepare_normalize_item_source_json_with_cleaned_body(
		source_json,
		site_name=_SITE_NAME,
	)
	return {
		"source_json": source_json,
		"llm_source_json": llm_source_json or source_json,
		"product_category_table": state.get("product_category_table"),
		"template": _build_full_item_template(),
		"direct_announcement_name": direct_announcement_name,
		"cleaned_announcement_content": cleaned_announcement_content,
	}


async def _extract_project_name_from_title(state: NormalizeItemGraphState) -> NormalizeItemGraphState:
	return {
		"title_project_name": await extract_project_name_from_title_text(
			str(state.get("direct_announcement_name") or ""),
			site_name=_SITE_NAME,
		)
	}


async def _extract_meta(state: NormalizeItemGraphState) -> NormalizeItemGraphState:
	meta_fields = await _extract_normalize_item_fields(
		state.get("llm_source_json", "") or state.get("source_json", ""),
		stage="meta",
		product_category_table=None,
	)
	was_truncated = bool(meta_fields.pop(_INPUT_TRUNCATED_META_KEY, False))
	return {
		"meta_fields": meta_fields,
		"meta_input_truncated": was_truncated,
	}


async def _extract_contacts(state: NormalizeItemGraphState) -> NormalizeItemGraphState:
	contacts_fields = await _extract_normalize_item_fields(
		state.get("llm_source_json", "") or state.get("source_json", ""),
		stage="contacts",
		product_category_table=None,
	)
	was_truncated = bool(contacts_fields.pop(_INPUT_TRUNCATED_META_KEY, False))
	return {
		"contacts_fields": contacts_fields,
		"contacts_input_truncated": was_truncated,
	}


async def _extract_address_detail(state: NormalizeItemGraphState) -> NormalizeItemGraphState:
	address_detail_fields = await _extract_normalize_item_fields(
		state.get("llm_source_json", "") or state.get("source_json", ""),
		stage="address_detail",
		product_category_table=None,
	)
	was_truncated = bool(address_detail_fields.pop(_INPUT_TRUNCATED_META_KEY, False))
	return {
		"address_detail_fields": address_detail_fields,
		"address_detail_input_truncated": was_truncated,
	}


async def _extract_lots(state: NormalizeItemGraphState) -> NormalizeItemGraphState:
	lots_fields = await _extract_normalize_item_fields(
		state.get("llm_source_json", "") or state.get("source_json", ""),
		stage="lots",
		product_category_table=state.get("product_category_table"),
	)
	was_truncated = bool(lots_fields.pop(_INPUT_TRUNCATED_META_KEY, False))
	return {
		"lots_fields": lots_fields,
		"lots_input_truncated": was_truncated,
	}


def _merge_fields(state: NormalizeItemGraphState) -> NormalizeItemGraphState:
	template = dict(state.get("template") or _build_full_item_template())
	meta_fields = dict(state.get("meta_fields") or {})
	contacts_fields = dict(state.get("contacts_fields") or {})
	address_detail_fields = dict(state.get("address_detail_fields") or {})
	lots_fields = dict(state.get("lots_fields") or {})

	merged = dict(template)
	merged.update(meta_fields)
	merged.update(contacts_fields)
	merged.update(address_detail_fields)
	merged["lotProducts"] = lots_fields.get("lotProducts") or []
	merged["lotCandidates"] = lots_fields.get("lotCandidates") or []
	merged["inputTruncated"] = bool(
		state.get("meta_input_truncated")
		or state.get("contacts_input_truncated")
		or state.get("address_detail_input_truncated")
		or state.get("lots_input_truncated")
	)
	cleaned_announcement_content = str(state.get("cleaned_announcement_content") or "").strip()
	if cleaned_announcement_content:
		merged["announcementContent"] = cleaned_announcement_content
	direct_announcement_name = str(state.get("direct_announcement_name") or "").strip()
	if direct_announcement_name:
		merged["announcementName"] = direct_announcement_name
	title_project_name = str(state.get("title_project_name") or "").strip()
	if title_project_name:
		merged["projectName"] = title_project_name

	return {
		"merged_item": merged,
		"raw_announcement_type": str(meta_fields.get("announcementType") or merged.get("announcementType") or ""),
	}


def _normalize_schema(state: NormalizeItemGraphState) -> NormalizeItemGraphState:
	return {"item": _normalize_item_to_crawler_schema(dict(state.get("merged_item") or {}))}


async def _fill_product_categories(state: NormalizeItemGraphState) -> NormalizeItemGraphState:
	item = dict(state.get("item") or {})
	item["lotProducts"] = await fill_product_categories_after_lots(
		item.get("lotProducts"),
		site_name=_SITE_NAME,
		product_category_table=state.get("product_category_table"),
	)
	return {"item": item}


async def _repair_announcement_type(state: NormalizeItemGraphState) -> NormalizeItemGraphState:
	item = dict(state.get("item") or {})
	if (item.get("announcementType") or "").strip() in ANNOUNCEMENT_TYPES:
		return {"item": item}

	raw_announcement_type = str(
		state.get("raw_announcement_type")
		or item.get("announcementType")
		or (state.get("merged_item") or {}).get("announcementType")
		or ""
	)
	repaired = await repair_announcement_type(
		site_name=_SITE_NAME,
		announcement_title=item.get("announcementName"),
		announcement_content=item.get("announcementContent") or state.get("source_json", ""),
		raw_announcement_type=raw_announcement_type,
		max_retries=3,
	)
	if not repaired:
		raise AnnouncementTypeRepairError(
			"announcementType invalid after 3 attempts",
			raw_type=raw_announcement_type,
			max_retries=3,
		)
	item["announcementType"] = repaired
	return {"item": item}


async def _fill_estimated_amount(state: NormalizeItemGraphState) -> NormalizeItemGraphState:
	item = dict(state.get("item") or {})
	await fill_estimated_amount_after_lots(
		item,
		site_name=_SITE_NAME,
		fields_path=_FIELDS_PATH,
	)
	return {"item": item}


async def _extract_address_admin(state: NormalizeItemGraphState) -> NormalizeItemGraphState:
	item = dict(state.get("item") or {})
	try:
		address_fields = await extract_admin_divisions_from_details(
			buyer_address_detail=item.get("buyerAddressDetail", ""),
			project_address_detail=item.get("projectAddressDetail", ""),
			delivery_address_detail=item.get("deliveryAddressDetail", ""),
			original_item=item,
			max_retries=3,
		)
	except Exception as norm_err:
		logger.warning(f"/normalize_item 地址字段 LLM 提取失败（已跳过）: {norm_err}")
		return {"item": item, "address_fields": {}}

	item.update(address_fields)
	return {"item": item, "address_fields": address_fields}


def _compute_data_id(state: NormalizeItemGraphState) -> NormalizeItemGraphState:
	item = dict(state.get("item") or {})
	data_id = compute_data_id(item)
	item["dataId"] = data_id
	return {"item": item, "data_id": data_id}


def _finalize_output(state: NormalizeItemGraphState) -> NormalizeItemGraphState:
	item = dict(state.get("item") or {})
	data_id = str(state.get("data_id") or item.get("dataId") or "")
	if data_id:
		item["dataId"] = data_id
	return {"item": item}


def _build_core_graph():
	graph = StateGraph(NormalizeItemGraphState)
	graph.add_node("prepare_input", _prepare_input)
	graph.add_node("extract_project_name_from_title", _extract_project_name_from_title)
	graph.add_node("extract_meta", _extract_meta)
	graph.add_node("extract_contacts", _extract_contacts)
	graph.add_node("extract_address_detail", _extract_address_detail)
	graph.add_node("extract_lots", _extract_lots)
	graph.add_node("merge_fields", _merge_fields)
	graph.add_node("normalize_schema", _normalize_schema)
	graph.add_node("fill_product_categories", _fill_product_categories)
	graph.add_node("repair_announcement_type", _repair_announcement_type)
	graph.add_node("fill_estimated_amount", _fill_estimated_amount)

	graph.add_edge(START, "prepare_input")
	graph.add_edge("prepare_input", "extract_project_name_from_title")
	graph.add_edge("prepare_input", "extract_meta")
	graph.add_edge("prepare_input", "extract_contacts")
	graph.add_edge("prepare_input", "extract_address_detail")
	graph.add_edge("prepare_input", "extract_lots")
	graph.add_edge("extract_project_name_from_title", "merge_fields")
	graph.add_edge("extract_meta", "merge_fields")
	graph.add_edge("extract_contacts", "merge_fields")
	graph.add_edge("extract_address_detail", "merge_fields")
	graph.add_edge("extract_lots", "merge_fields")
	graph.add_edge("merge_fields", "normalize_schema")
	graph.add_edge("normalize_schema", "fill_product_categories")
	graph.add_edge("fill_product_categories", "repair_announcement_type")
	graph.add_edge("repair_announcement_type", "fill_estimated_amount")
	graph.add_edge("fill_estimated_amount", END)
	return graph.compile()


def _build_full_graph():
	graph = StateGraph(NormalizeItemGraphState)
	graph.add_node("prepare_input", _prepare_input)
	graph.add_node("extract_project_name_from_title", _extract_project_name_from_title)
	graph.add_node("extract_meta", _extract_meta)
	graph.add_node("extract_contacts", _extract_contacts)
	graph.add_node("extract_address_detail", _extract_address_detail)
	graph.add_node("extract_lots", _extract_lots)
	graph.add_node("merge_fields", _merge_fields)
	graph.add_node("normalize_schema", _normalize_schema)
	graph.add_node("fill_product_categories", _fill_product_categories)
	graph.add_node("repair_announcement_type", _repair_announcement_type)
	graph.add_node("fill_estimated_amount", _fill_estimated_amount)
	graph.add_node("extract_address_admin", _extract_address_admin)
	graph.add_node("compute_data_id", _compute_data_id)
	graph.add_node("finalize_output", _finalize_output)

	graph.add_edge(START, "prepare_input")
	graph.add_edge("prepare_input", "extract_project_name_from_title")
	graph.add_edge("prepare_input", "extract_meta")
	graph.add_edge("prepare_input", "extract_contacts")
	graph.add_edge("prepare_input", "extract_address_detail")
	graph.add_edge("prepare_input", "extract_lots")
	graph.add_edge("extract_project_name_from_title", "merge_fields")
	graph.add_edge("extract_meta", "merge_fields")
	graph.add_edge("extract_contacts", "merge_fields")
	graph.add_edge("extract_address_detail", "merge_fields")
	graph.add_edge("extract_lots", "merge_fields")
	graph.add_edge("merge_fields", "normalize_schema")
	graph.add_edge("normalize_schema", "fill_product_categories")
	graph.add_edge("fill_product_categories", "repair_announcement_type")
	graph.add_edge("repair_announcement_type", "fill_estimated_amount")
	graph.add_edge("fill_estimated_amount", "extract_address_admin")
	graph.add_edge("extract_address_admin", "compute_data_id")
	graph.add_edge("compute_data_id", "finalize_output")
	graph.add_edge("finalize_output", END)
	return graph.compile()


_CORE_GRAPH = _build_core_graph()
_FULL_GRAPH = _build_full_graph()


async def run_normalize_item_core_graph(
	source_json: str,
	*,
	product_category_table: str | None = None,
) -> dict[str, Any]:
	src = (source_json or "").strip()
	if not src:
		return _build_full_item_template()

	final_state = await _CORE_GRAPH.ainvoke(
		{
			"source_json": src,
			"product_category_table": product_category_table,
		}
	)
	return dict(final_state.get("item") or _build_full_item_template())


async def run_normalize_item_graph(
	source_json: str,
	*,
	product_category_table: str | None = None,
) -> dict[str, Any]:
	src = (source_json or "").strip()
	if not src:
		item = _build_full_item_template()
		try:
			address_fields = await extract_admin_divisions_from_details(
				buyer_address_detail=item.get("buyerAddressDetail", ""),
				project_address_detail=item.get("projectAddressDetail", ""),
				delivery_address_detail=item.get("deliveryAddressDetail", ""),
				original_item=item,
				max_retries=3,
			)
			item.update(address_fields)
		except Exception as norm_err:
			logger.warning(f"/normalize_item 地址字段 LLM 提取失败（已跳过）: {norm_err}")
		item["dataId"] = compute_data_id(item)
		return item

	final_state = await _FULL_GRAPH.ainvoke(
		{
			"source_json": src,
			"product_category_table": product_category_table,
		}
	)
	return dict(final_state.get("item") or _build_full_item_template())


__all__ = [
	"NormalizeItemGraphState",
	"run_normalize_item_core_graph",
	"run_normalize_item_graph",
]
