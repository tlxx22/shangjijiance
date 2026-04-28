from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from .address_normalizer import extract_admin_divisions_from_details
from .algorithm_version import ALGORITHM_VERSION
from .announcement_type_repair import repair_announcement_type
from .custom_tools import (
	_INPUT_TRUNCATED_META_KEY,
	_wait_for_detail_content_ready,
	click_show_full_info,
	compute_data_id,
	extract_fields_from_html,
	extract_page_content,
	get_unique_filename,
	llm_is_engineering_machinery_project,
	normalize_date_ymd,
)
from .estimated_amount_deriver import fill_estimated_amount_after_lots
from .field_schemas import (
	supplement_lot_products_from_candidates,
	try_normalize_announcement_type,
)
from .logger_config import get_logger
from .product_category_postprocessor import fill_product_categories_after_lots

logger = get_logger()


class CrawlDetailGraphState(TypedDict, total=False):
	browser_session: Any
	site_name: str
	output_dir: Path
	title: str
	date: str
	product_category_table: str | None
	engineering_machinery_only: bool
	on_item_saved: Callable[[dict[str, Any]], Any] | None
	locked_list_url: str | None
	seen_detail_keys: set[str]

	cdp_session: Any
	detail_url: str
	file_date: str
	dedup_key: str
	announcement_content: str

	meta_fields: dict[str, Any]
	meta_input_truncated: bool
	contacts_fields: dict[str, Any]
	contacts_input_truncated: bool
	address_detail_fields: dict[str, Any]
	address_detail_input_truncated: bool
	lots_fields: dict[str, Any]
	lots_input_truncated: bool
	lot_products: list[dict[str, Any]]
	lot_candidates: list[dict[str, Any]]

	result_data: dict[str, Any]
	filename: str

	outcome_code: str
	outcome_message: str
	action_result: dict[str, Any]


def _should_stop(state: CrawlDetailGraphState) -> bool:
	return bool((state.get("outcome_code") or "").strip())


def _set_terminal(
	outcome_code: str,
	*,
	extracted_content: str,
	error: str | None = None,
	long_term_memory: str | None = None,
) -> CrawlDetailGraphState:
	action_result: dict[str, Any] = {"extracted_content": extracted_content}
	if error is not None:
		action_result["error"] = error
	if long_term_memory is not None:
		action_result["long_term_memory"] = long_term_memory
	return {
		"outcome_code": outcome_code,
		"outcome_message": extracted_content,
		"action_result": action_result,
	}


async def _prepare_detail_context(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state):
		return {}

	output_dir = state["output_dir"]
	output_dir.mkdir(parents=True, exist_ok=True)

	detail_url = "unknown"
	cdp_session = await state["browser_session"].get_or_create_cdp_session()
	try:
		url_result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={"expression": "location.href", "returnByValue": True},
			session_id=cdp_session.session_id,
		)
		detail_url = url_result.get("result", {}).get("value", "unknown")
	except Exception as e:
		logger.warning(f"获取URL失败: {e}")

	file_date = normalize_date_ymd(state["date"]) or str(state["date"]).replace("/", "-").replace(".", "-")
	return {
		"cdp_session": cdp_session,
		"detail_url": detail_url,
		"file_date": file_date,
	}


def _guard_on_detail_page(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state):
		return {}

	try:
		from urllib.parse import urlsplit

		locked_list_url = (state.get("locked_list_url") or "").strip()
		detail_url = (state.get("detail_url") or "").strip()
		if locked_list_url and detail_url and detail_url not in {"unknown", ""}:
			list_parts = urlsplit(locked_list_url)
			cur_parts = urlsplit(detail_url)
			same_origin_path = (
				list_parts.scheme == cur_parts.scheme
				and list_parts.netloc == cur_parts.netloc
				and list_parts.path == cur_parts.path
			)
			if same_origin_path:
				list_frag = (list_parts.fragment or "").strip()
				cur_frag = (cur_parts.fragment or "").strip()
				if list_frag or cur_frag:
					same_fragment = list_frag == cur_frag
				else:
					same_fragment = True
				if not same_fragment:
					same_origin_path = False
			if same_origin_path:
				logger.warning(
					f"[{state['site_name']}] ⚠️ save_detail 在列表页被调用（URL 未进入详情页）: {detail_url}"
				)
				return _set_terminal(
					"not_on_detail_page",
					extracted_content=(
						"当前仍在列表页（URL 未进入详情页），请改用 open_and_save(标题链接index, title, date) "
						"或先切换到真正的详情页标签后再调用 save_detail。"
					),
					error="not_on_detail_page",
				)
	except Exception:
		pass

	return {}


def _build_dedup_key(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state):
		return {}

	detail_url = (state.get("detail_url") or "").strip()
	dedup_key = detail_url if detail_url and detail_url != "unknown" else f"{state['title'].strip()}|{state['file_date']}"
	return {"dedup_key": dedup_key}


def _skip_if_duplicate(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state):
		return {}

	dedup_key = state.get("dedup_key") or ""
	if dedup_key in state["seen_detail_keys"]:
		logger.info(f"[{state['site_name']}] ↩︎ 重复公告已跳过: {state['title'][:40]}... ({dedup_key[:80]})")
		return _set_terminal(
			"skipped_duplicate",
			extracted_content="skipped_duplicate",
			long_term_memory=f"重复公告已跳过: {state['title'][:30]}...",
		)
	return {}


async def _expand_and_wait_detail(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state):
		return {}

	await click_show_full_info(state["browser_session"])
	await _wait_for_detail_content_ready(
		state["browser_session"],
		state["site_name"],
		cdp_session=state.get("cdp_session"),
	)
	return {}


async def _extract_content(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state):
		return {}

	announcement_content = await extract_page_content(
		state["browser_session"],
		state["site_name"],
		cdp_session=state.get("cdp_session"),
	)
	if not announcement_content:
		logger.warning(f"[{state['site_name']}] 提取公告原文(HTML)失败: 内容为空")
		return {
			"announcement_content": "",
			**_set_terminal(
				"extract_content_empty",
				extracted_content=f"提取公告原文失败: {state['title']}",
				error="提取公告原文失败",
			),
		}
	return {"announcement_content": announcement_content}


async def _extract_meta(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state):
		return {}

	meta_fields = await extract_fields_from_html(
		state.get("announcement_content", ""),
		site_name=state["site_name"],
		stage="meta",
	)
	was_truncated = bool(meta_fields.pop(_INPUT_TRUNCATED_META_KEY, False))
	meta_fields.pop("updateDate", None)
	return {
		"meta_fields": meta_fields,
		"meta_input_truncated": was_truncated,
	}


def _route_after_extract_content(state: CrawlDetailGraphState):
	if state.get("engineering_machinery_only"):
		return "extract_meta_engineering"
	return [
		"extract_meta_parallel",
		"extract_contacts",
		"extract_address_detail",
		"extract_lots",
	]


async def _check_engineering_scope(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state) or not state.get("engineering_machinery_only"):
		return {}

	project_name = str((state.get("meta_fields") or {}).get("projectName") or "").strip()
	if not project_name:
		return {}

	decision, reason = await llm_is_engineering_machinery_project(
		project_name,
		title=state["title"],
		site_name=state["site_name"],
	)
	if decision is False:
		state["seen_detail_keys"].add(str(state.get("dedup_key") or ""))
		logger.info(
			f"[{state['site_name']}] ↩︎ 工程机械类筛选已跳过: {state['title'][:40]}... "
			f"(projectName={project_name[:60]!r})"
			+ (f" reason={reason}" if reason else "")
		)
		return _set_terminal(
			"skipped_non_gongchengjixie",
			extracted_content="skipped_non_gongchengjixie",
			long_term_memory=f"跳过（非工程机械类）: {state['title'][:30]}...",
		)
	if decision is None:
		logger.warning(
			f"[{state['site_name']}] 工程机械类判定无结果，默认保留: {state['title'][:40]}..."
			+ (f" reason={reason}" if reason else "")
		)
	return {}


def _route_after_check_engineering_scope(state: CrawlDetailGraphState):
	return [
		"extract_contacts",
		"extract_address_detail",
		"extract_lots",
	]


async def _extract_contacts(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state):
		return {}
	contacts_fields = await extract_fields_from_html(
		state.get("announcement_content", ""),
		site_name=state["site_name"],
		stage="contacts",
	)
	was_truncated = bool(contacts_fields.pop(_INPUT_TRUNCATED_META_KEY, False))
	return {
		"contacts_fields": contacts_fields,
		"contacts_input_truncated": was_truncated,
	}


async def _extract_address_detail(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state):
		return {}
	address_detail_fields = await extract_fields_from_html(
		state.get("announcement_content", ""),
		site_name=state["site_name"],
		stage="address_detail",
	)
	was_truncated = bool(address_detail_fields.pop(_INPUT_TRUNCATED_META_KEY, False))
	return {
		"address_detail_fields": address_detail_fields,
		"address_detail_input_truncated": was_truncated,
	}


async def _extract_lots(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state):
		return {}
	lots_fields = await extract_fields_from_html(
		state.get("announcement_content", ""),
		site_name=state["site_name"],
		stage="lots",
		product_category_table=state.get("product_category_table"),
	)
	was_truncated = bool(lots_fields.pop(_INPUT_TRUNCATED_META_KEY, False))
	return {
		"lots_fields": lots_fields,
		"lots_input_truncated": was_truncated,
	}


async def _postprocess_lots(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state):
		return {}

	lots_fields = dict(state.get("lots_fields") or {})
	lot_products = lots_fields.get("lotProducts") or []
	lot_candidates = lots_fields.get("lotCandidates") or []
	if not isinstance(lot_products, list):
		lot_products = []
	if not isinstance(lot_candidates, list):
		lot_candidates = []

	lot_products = supplement_lot_products_from_candidates(lot_products, lot_candidates)
	lot_products = await fill_product_categories_after_lots(
		lot_products,
		site_name=state["site_name"],
		product_category_table=state.get("product_category_table"),
	)
	return {
		"lot_products": lot_products,
		"lot_candidates": lot_candidates,
	}


def _merge_result_data(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state):
		return {}

	result_data = {
		"version": ALGORITHM_VERSION,
		"inputTruncated": bool(
			state.get("meta_input_truncated")
			or state.get("contacts_input_truncated")
			or state.get("address_detail_input_truncated")
			or state.get("lots_input_truncated")
		),
		"announcementUrl": state.get("detail_url") or "unknown",
		"announcementName": state["title"],
		"announcementContent": state.get("announcement_content", ""),
		**(state.get("meta_fields") or {}),
		**(state.get("contacts_fields") or {}),
		**(state.get("address_detail_fields") or {}),
		"lotProducts": state.get("lot_products") or [],
		"lotCandidates": state.get("lot_candidates") or [],
	}
	if not str(result_data.get("announcementDate") or "").strip():
		list_page_date = normalize_date_ymd(state.get("date") or "")
		if list_page_date:
			result_data["announcementDate"] = list_page_date

	return {"result_data": result_data}


async def _repair_announcement_type(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state):
		return {}

	result_data = dict(state.get("result_data") or {})
	raw_announcement_type = result_data.get("announcementType")
	normalized_type = try_normalize_announcement_type(raw_announcement_type)
	if not normalized_type:
		normalized_type = await repair_announcement_type(
			site_name=state["site_name"],
			announcement_title=state["title"],
			announcement_content=state.get("announcement_content", ""),
			raw_announcement_type=str(raw_announcement_type or ""),
			max_retries=3,
		)

	if not normalized_type:
		logger.warning(
			f"[{state['site_name']}] 公告类别修复失败（已达上限 3 次），已跳过: {state['title'][:60]}... "
			f"(raw={str(raw_announcement_type or '')!r}, url={str(state.get('detail_url') or '')})"
		)
		state["seen_detail_keys"].add(str(state.get("dedup_key") or ""))
		return _set_terminal(
			"skipped_invalid_announcement_type",
			extracted_content="skipped_invalid_announcement_type",
			long_term_memory=f"跳过（公告类型无法归一化）: {state['title'][:30]}...",
		)

	result_data["announcementType"] = normalized_type
	return {"result_data": result_data}


async def _fill_estimated_amount(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state):
		return {}

	result_data = dict(state.get("result_data") or {})
	await fill_estimated_amount_after_lots(
		result_data,
		site_name=state["site_name"],
		fields_path="extract_fields.yaml",
	)
	return {"result_data": result_data}


async def _extract_address_admin(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state):
		return {}

	result_data = dict(state.get("result_data") or {})
	try:
		addr = await extract_admin_divisions_from_details(
			buyer_address_detail=result_data.get("buyerAddressDetail", ""),
			project_address_detail=result_data.get("projectAddressDetail", ""),
			delivery_address_detail=result_data.get("deliveryAddressDetail", ""),
			original_item=result_data,
			max_retries=3,
		)
		result_data.update(addr)
	except Exception as norm_err:
		logger.warning(f"[{state['site_name']}] 地址字段 LLM 提取失败（已跳过）: {norm_err}")
	return {"result_data": result_data}


def _compute_data_id(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state):
		return {}

	result_data = dict(state.get("result_data") or {})
	result_data["dataId"] = compute_data_id(result_data)
	return {"result_data": result_data}


async def _persist_and_emit(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state):
		return {}

	filename = get_unique_filename(state["output_dir"], state["title"], state["file_date"])
	result_data = dict(state.get("result_data") or {})
	json_path = state["output_dir"] / f"{filename}.json"
	with open(json_path, "w", encoding="utf-8") as f:
		json.dump(result_data, f, ensure_ascii=False, indent=2)

	state["seen_detail_keys"].add(str(state.get("dedup_key") or ""))
	logger.info(f"[{state['site_name']}] ✓ 元数据已保存: {json_path.name}")

	on_item_saved = state.get("on_item_saved")
	if on_item_saved:
		try:
			ret = on_item_saved(result_data)
			if asyncio.iscoroutine(ret):
				await ret
		except Exception as cb_err:
			logger.warning(f"[{state['site_name']}] 回调执行失败: {cb_err}")

	return {
		"filename": filename,
		"result_data": result_data,
	}


def _finalize_outcome(state: CrawlDetailGraphState) -> CrawlDetailGraphState:
	if _should_stop(state):
		return {}

	filename = state.get("filename") or ""
	title = state.get("title") or ""
	return {
		**_set_terminal(
			"success",
			extracted_content=f"✓ 已保存: {filename}.json",
			long_term_memory=f"已保存详情页正文(HTML): {title[:30]}...",
		),
	}


def _build_crawl_detail_graph():
	graph = StateGraph(CrawlDetailGraphState)
	graph.add_node("prepare_detail_context", _prepare_detail_context)
	graph.add_node("guard_on_detail_page", _guard_on_detail_page)
	graph.add_node("build_dedup_key", _build_dedup_key)
	graph.add_node("skip_if_duplicate", _skip_if_duplicate)
	graph.add_node("expand_and_wait_detail", _expand_and_wait_detail)
	graph.add_node("extract_content", _extract_content)
	graph.add_node("extract_meta_parallel", _extract_meta)
	graph.add_node("extract_meta_engineering", _extract_meta)
	graph.add_node("check_engineering_scope", _check_engineering_scope)
	graph.add_node("extract_contacts", _extract_contacts)
	graph.add_node("extract_address_detail", _extract_address_detail)
	graph.add_node("extract_lots", _extract_lots)
	graph.add_node("postprocess_lots", _postprocess_lots)
	graph.add_node("merge_result_data_parallel", _merge_result_data)
	graph.add_node("merge_result_data_engineering", _merge_result_data)
	graph.add_node("repair_announcement_type", _repair_announcement_type)
	graph.add_node("fill_estimated_amount", _fill_estimated_amount)
	graph.add_node("extract_address_admin", _extract_address_admin)
	graph.add_node("compute_data_id", _compute_data_id)
	graph.add_node("persist_and_emit", _persist_and_emit)
	graph.add_node("finalize_outcome", _finalize_outcome)

	graph.add_edge(START, "prepare_detail_context")
	graph.add_edge("prepare_detail_context", "guard_on_detail_page")
	graph.add_edge("guard_on_detail_page", "build_dedup_key")
	graph.add_edge("build_dedup_key", "skip_if_duplicate")
	graph.add_edge("skip_if_duplicate", "expand_and_wait_detail")
	graph.add_edge("expand_and_wait_detail", "extract_content")
	graph.add_conditional_edges("extract_content", _route_after_extract_content)
	graph.add_edge("extract_meta_engineering", "check_engineering_scope")
	graph.add_conditional_edges("check_engineering_scope", _route_after_check_engineering_scope)
	graph.add_edge("extract_lots", "postprocess_lots")
	graph.add_edge(["extract_meta_parallel", "extract_contacts", "extract_address_detail", "postprocess_lots"], "merge_result_data_parallel")
	graph.add_edge(["extract_meta_engineering", "extract_contacts", "extract_address_detail", "postprocess_lots"], "merge_result_data_engineering")
	graph.add_edge("merge_result_data_parallel", "repair_announcement_type")
	graph.add_edge("merge_result_data_engineering", "repair_announcement_type")
	graph.add_edge("repair_announcement_type", "fill_estimated_amount")
	graph.add_edge("fill_estimated_amount", "extract_address_admin")
	graph.add_edge("extract_address_admin", "compute_data_id")
	graph.add_edge("compute_data_id", "persist_and_emit")
	graph.add_edge("persist_and_emit", "finalize_outcome")
	graph.add_edge("finalize_outcome", END)
	return graph.compile()


_CRAWL_DETAIL_GRAPH = _build_crawl_detail_graph()


async def run_crawl_detail_graph(
	*,
	browser_session: Any,
	site_name: str,
	output_dir: Path,
	title: str,
	date: str,
	product_category_table: str | None,
	engineering_machinery_only: bool,
	on_item_saved: Callable[[dict[str, Any]], Any] | None,
	locked_list_url: str | None,
	seen_detail_keys: set[str],
) -> dict[str, Any]:
	final_state = await _CRAWL_DETAIL_GRAPH.ainvoke(
		{
			"browser_session": browser_session,
			"site_name": site_name,
			"output_dir": output_dir,
			"title": title,
			"date": date,
			"product_category_table": product_category_table,
			"engineering_machinery_only": engineering_machinery_only,
			"on_item_saved": on_item_saved,
			"locked_list_url": locked_list_url,
			"seen_detail_keys": seen_detail_keys,
		}
	)
	return {
		"outcome_code": final_state.get("outcome_code") or "",
		"outcome_message": final_state.get("outcome_message") or "",
		"detail_url": final_state.get("detail_url") or "",
		"action_result": dict(final_state.get("action_result") or {}),
		"filename": final_state.get("filename") or "",
		"result_data": dict(final_state.get("result_data") or {}),
	}


__all__ = [
	"CrawlDetailGraphState",
	"run_crawl_detail_graph",
]
