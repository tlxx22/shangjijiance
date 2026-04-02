from __future__ import annotations

import json
import os
from typing import Any

import requests
from openai import OpenAI

import trans
from src.logger_config import get_logger


DEFAULT_OPENAI_PARENT_ORG_MODEL = "gpt-5.2"
DEFAULT_SANY_PARENT_ORG_MODEL = "deepseek-v3.2"
BOCHA_WEB_SEARCH_URL = "https://api.bochaai.com/v1/web-search"
MAX_TOOL_ROUNDS = 10
BOCHA_RESULT_COUNT = 8
MAX_RESULT_TEXT_LEN = 600

logger = get_logger()


class ParentOrgUpstreamError(Exception):
	"""Raised when the upstream model response is invalid for this endpoint."""


def _normalize_base_url(url: str) -> str:
	return (url or "").rstrip("/")


def _get_sany_headers() -> dict[str, str] | None:
	x_ai_server = os.getenv("SANY_X_AI_SERVER") or os.getenv("SANY_AI_SERVER")
	if not x_ai_server:
		return None
	return {"X-ai-server": x_ai_server}


def _get_value(obj: Any, key: str, default: Any = None) -> Any:
	if obj is None:
		return default
	if isinstance(obj, dict):
		return obj.get(key, default)
	return getattr(obj, key, default)


def _strip_code_fences(text: str) -> str:
	s = (text or "").strip()
	if not s.startswith("```"):
		return s
	lines = s.splitlines()
	if lines:
		lines = lines[1:]
	while lines and lines[-1].strip().startswith("```"):
		lines.pop()
	return "\n".join(lines).strip()


def _parse_json_object(text: str) -> dict[str, Any]:
	cleaned = _strip_code_fences(text)
	if not cleaned:
		raise ParentOrgUpstreamError("parent_org_name upstream returned empty output")

	decoder = json.JSONDecoder()
	candidates = [cleaned]
	first_brace = cleaned.find("{")
	if first_brace > 0:
		candidates.append(cleaned[first_brace:])

	for candidate in candidates:
		try:
			obj, _ = decoder.raw_decode(candidate)
		except json.JSONDecodeError:
			continue
		if isinstance(obj, dict):
			return obj

	raise ParentOrgUpstreamError("parent_org_name upstream returned non-JSON output")


def _truncate(text: Any, max_len: int = MAX_RESULT_TEXT_LEN) -> str:
	value = "" if text is None else str(text)
	if len(value) <= max_len:
		return value
	return value[: max_len - 3] + "..."


def _normalize_bocha_result(item: dict[str, Any]) -> dict[str, str] | None:
	url = item.get("url")
	if not isinstance(url, str) or not url.strip():
		return None
	return {
		"title": _truncate(item.get("name") or ""),
		"url": url.strip(),
		"snippet": _truncate(item.get("snippet") or ""),
		"summary": _truncate(item.get("summary") or ""),
		"siteName": _truncate(item.get("siteName") or ""),
	}


def _extract_bocha_web_results(payload: dict[str, Any]) -> list[dict[str, str]]:
	candidates: list[Any] = []
	data = payload.get("data")
	if isinstance(data, dict):
		web_pages = data.get("webPages")
		if isinstance(web_pages, dict) and isinstance(web_pages.get("value"), list):
			candidates.extend(web_pages["value"])
		if isinstance(data.get("value"), list):
			candidates.extend(data["value"])

	web_pages = payload.get("webPages")
	if isinstance(web_pages, dict) and isinstance(web_pages.get("value"), list):
		candidates.extend(web_pages["value"])

	if isinstance(payload.get("value"), list):
		candidates.extend(payload["value"])

	results: list[dict[str, str]] = []
	seen: set[str] = set()
	for raw_item in candidates:
		if not isinstance(raw_item, dict):
			continue
		normalized = _normalize_bocha_result(raw_item)
		if not normalized:
			continue
		url = normalized["url"]
		if url in seen:
			continue
		seen.add(url)
		results.append(normalized)
	return results


def _bocha_tool_payload(results: list[dict[str, str]]) -> dict[str, Any]:
	return {
		"results": [
			{
				"title": item["title"],
				"url": item["url"],
				"siteName": item["siteName"],
				"snippet": item["snippet"],
				"summary": item["summary"],
			}
			for item in results
		]
	}


def _run_bocha_web_search(query: str) -> list[dict[str, str]]:
	api_key = os.getenv("BOCHA_API_KEY")
	if not api_key:
		raise RuntimeError("Missing BOCHA_API_KEY.")

	query_text = (query or "").strip()
	if not query_text:
		raise ParentOrgUpstreamError("bocha_web_search called with empty query")

	try:
		resp = requests.post(
			BOCHA_WEB_SEARCH_URL,
			headers={
				"Authorization": f"Bearer {api_key}",
				"Content-Type": "application/json",
			},
			json={
				"query": query_text,
				"summary": True,
				"freshness": "noLimit",
				"count": BOCHA_RESULT_COUNT,
			},
			timeout=30,
		)
		resp.raise_for_status()
	except requests.RequestException as exc:
		raise ParentOrgUpstreamError(f"bocha search request failed: {exc}") from exc

	try:
		payload = resp.json()
	except ValueError as exc:
		raise ParentOrgUpstreamError("bocha search returned non-JSON response") from exc

	results = _extract_bocha_web_results(payload if isinstance(payload, dict) else {})
	logger.info(f"bocha_web_search query={query_text!r} hits={len(results)}")
	return results


def _assistant_message_dict(message: Any) -> dict[str, Any]:
	out: dict[str, Any] = {"role": "assistant"}
	content = _get_value(message, "content")
	if content is not None:
		out["content"] = content

	tool_calls = _get_value(message, "tool_calls", None) or []
	if tool_calls:
		out["tool_calls"] = [
			{
				"id": _get_value(tool_call, "id"),
				"type": _get_value(tool_call, "type", "function"),
				"function": {
					"name": _get_value(_get_value(tool_call, "function"), "name"),
					"arguments": _get_value(_get_value(tool_call, "function"), "arguments", ""),
				},
			}
			for tool_call in tool_calls
		]
	return out


def _extract_message_content(message: Any) -> str:
	content = _get_value(message, "content", None)
	if isinstance(content, str):
		return content.strip()

	if isinstance(content, list):
		parts: list[str] = []
		for item in content:
			if isinstance(item, str):
				parts.append(item)
			else:
				text = _get_value(item, "text", None)
				if isinstance(text, str):
					parts.append(text)
		return "\n".join(parts).strip()

	return ""


def _parse_tool_arguments(arguments: str) -> dict[str, Any]:
	try:
		parsed = json.loads(arguments or "{}")
	except json.JSONDecodeError as exc:
		raise ParentOrgUpstreamError("bocha_web_search arguments are not valid JSON") from exc
	if not isinstance(parsed, dict):
		raise ParentOrgUpstreamError("bocha_web_search arguments must be a JSON object")
	return parsed


def _validate_payload(payload: dict[str, Any], source_index: dict[str, dict[str, str]]) -> tuple[str, float, list[dict[str, str]]]:
	parent_org_name = payload.get("parentOrgName")
	if not isinstance(parent_org_name, str):
		raise ParentOrgUpstreamError("parent_org_name upstream returned invalid parentOrgName")

	confidence = payload.get("confidence")
	if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
		raise ParentOrgUpstreamError("parent_org_name upstream returned invalid confidence")

	confidence_value = float(confidence)
	if confidence_value < 0 or confidence_value > 1:
		raise ParentOrgUpstreamError("parent_org_name upstream returned confidence outside [0, 1]")

	source_urls = payload.get("sourceUrls")
	if not isinstance(source_urls, list) or any(not isinstance(url, str) for url in source_urls):
		raise ParentOrgUpstreamError("parent_org_name upstream returned invalid sourceUrls")

	sources: list[dict[str, str]] = []
	seen: set[str] = set()
	for raw_url in source_urls:
		url = raw_url.strip()
		if not url or url in seen:
			continue
		source = source_index.get(url)
		if not source:
			continue
		seen.add(url)
		sources.append({"title": source["title"], "url": source["url"]})

	if not sources:
		logger.warning(
			"parent_org_name sourceUrls mismatch: model returned no URLs matching service-side search results"
		)
		sources = [{"title": "匹配失败", "url": "匹配失败"}]

	return parent_org_name, confidence_value, sources


def _validate_affiliate_payload(payload: dict[str, Any]) -> str:
	affiliate_org_name = payload.get("affiliateOrgName")
	if not isinstance(affiliate_org_name, str):
		raise ParentOrgUpstreamError("parent_org_name upstream returned invalid affiliateOrgName")

	affiliate_org_name = affiliate_org_name.strip()
	if not affiliate_org_name:
		raise ParentOrgUpstreamError("parent_org_name upstream returned empty affiliateOrgName")

	return affiliate_org_name


def _get_client_config() -> tuple[str, OpenAI, str]:
	route = getattr(trans, "ROUTE", "official")

	if route == "sany":
		api_key = os.getenv("SANY_AI_GATEWAY_KEY") or os.getenv("SANY_AI_GATEWAY_API_KEY")
		if not api_key:
			raise RuntimeError("Missing SANY gateway api key. Set env var SANY_AI_GATEWAY_KEY.")
		base_url = _normalize_base_url(os.getenv("SANY_AI_GATEWAY_BASE_URL", "https://agent-api-test.sany.com.cn/ai-api"))
		model_name = (
			os.getenv("SANY_PARENT_ORG_MODEL")
			or os.getenv("SANY_EXTRACT_MODEL")
			or DEFAULT_SANY_PARENT_ORG_MODEL
		).strip()
		client = OpenAI(api_key=api_key, base_url=base_url, default_headers=_get_sany_headers())
		return route, client, model_name

	if route == "openai":
		api_key = os.getenv("OPENAI_API_KEY")
		if not api_key:
			raise RuntimeError("Missing OpenAI API key. Set env var OPENAI_API_KEY.")
		base_url = _normalize_base_url(os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
		model_name = (
			os.getenv("OPENAI_PARENT_ORG_MODEL")
			or os.getenv("OPENAI_MODEL")
			or DEFAULT_OPENAI_PARENT_ORG_MODEL
		).strip()
		client = OpenAI(api_key=api_key, base_url=base_url)
		return route, client, model_name

	raise RuntimeError("parent_org_name web search is only supported when ROUTE is 'openai' or 'sany'")


def _tool_schema() -> list[dict[str, Any]]:
	return [
		{
			"type": "function",
			"function": {
				"name": "bocha_web_search",
				"description": "Search the web for authoritative pages about the target organization and its nearest parent organization.",
				"parameters": {
					"type": "object",
					"properties": {
						"query": {
							"type": "string",
							"description": "The exact web search query to send to Bocha.",
						}
					},
					"required": ["query"],
					"additionalProperties": False,
				},
			},
		}
	]


def resolve_affiliate_org_name(org_name: str) -> str:
	original_org_name = (org_name or "").strip()
	if not original_org_name:
		return original_org_name

	try:
		route, client, model_name = _get_client_config()
		response = client.chat.completions.create(
			model=model_name,
			messages=[
				{
					"role": "system",
					"content": (
						"You identify the affiliate company name for an input organization name.\n\n"
						"Return ONLY one JSON object with exactly this field:\n"
						"{\n"
						'  "affiliateOrgName": "string"\n'
						"}\n\n"
						"Rules:\n"
						"- The goal is the company subject this name belongs to, not the parent company and not the ultimate controller.\n"
						"- If the input is a department or internal functional unit under a company, return the company subject only.\n"
						"- If the input is a project-level internal organization under a company, such as a 项目经理部, 项目部, 指挥部, 总承包部, or similar project organization, return the company subject only.\n"
						"- If the input already is a company name, keep it unchanged.\n"
						"- If the input is a branch company or office, keep the full branch or office name unchanged.\n"
						"- Do not return Markdown, explanations, or extra fields.\n"
					),
				},
				{
					"role": "user",
					"content": (
						"请识别这个名称对应的“所属公司”。\n"
						"要求：\n"
						"1. 像“xxx公司采购部”这种，只保留所属公司“xxx公司”；\n"
						"2. 像“xxx公司”这种，直接返回原名称；\n"
						"3. 像“xxx公司山东分公司”或“xxx有限公司北京办事处”这种，保留完整名称，不要上提到总公司；\n"
						"4. 像“xxx公司某项目经理部”“xxx公司某标段项目部”“xxx公司某工程指挥部”这种项目组织，只保留所属公司“xxx公司”；\n"
						"5. 如果输入中能识别到明确的公司主体，就返回该公司主体，不要因为后面跟着项目、标段、经理部、项目部、指挥部等字样就保留整串名称。\n"
						f"原始输入：{original_org_name}"
					),
				},
			],
		)
		choices = _get_value(response, "choices", None) or []
		if not choices:
			raise ParentOrgUpstreamError("parent_org_name affiliate upstream returned no choices")

		message = _get_value(choices[0], "message", None)
		if message is None:
			raise ParentOrgUpstreamError("parent_org_name affiliate upstream returned no message")

		payload = _parse_json_object(_extract_message_content(message))
		affiliate_org_name = _validate_affiliate_payload(payload)
		logger.info(
			f"parent_org_name affiliate orgName={original_org_name!r} affiliateOrgName={affiliate_org_name!r} "
			f"route={route} model={model_name}"
		)
		return affiliate_org_name
	except Exception as exc:
		logger.warning(
			f"parent_org_name affiliate fallback orgName={original_org_name!r}: {exc}"
		)
		return original_org_name


def resolve_parent_org_name(org_name: str) -> dict[str, Any]:
	route, client, model_name = _get_client_config()

	messages: list[dict[str, Any]] = [
		{
			"role": "system",
			"content": (
				"You resolve the nearest parent organization for a company or organization name.\n\n"
				"You MUST call the function tool bocha_web_search before giving the final answer.\n"
				"The goal is the nearest upper-level organization, not the ultimate group and not the ultimate controller.\n\n"
				"Return ONLY one JSON object with exactly these fields:\n"
				"{\n"
				'  "parentOrgName": "string",\n'
				'  "confidence": 0.0,\n'
				'  "sourceUrls": ["https://..."]\n'
				"}\n\n"
				"Rules:\n"
				'- Use confidence to reflect uncertainty; do not use empty string only because confidence is low.\n'
				'- If the answer would otherwise be a placeholder such as "无", "未知", "暂无", "不详", "N/A", or similar text, set "parentOrgName" to "" instead.\n'
				'- "parentOrgName" must be an organization or company name, not a person name, not a contact, and not a job title or role such as chairman, legal representative, or general manager; if you would otherwise return a person name or role title, set "parentOrgName" to "" instead.\n'
				'- Prefer the full official or legal organization name instead of an abbreviation, alias, or historical short name whenever the sources support the full name.\n'
				'- If the sources show both a short name and a full name for the same organization, return the full name.\n'
				"- sourceUrls must contain only real URLs returned by the tool.\n"
				"- Always return the single most suitable result.\n"
				"- Do not return Markdown, explanations, or extra fields.\n"
			),
		},
		{
			"role": "user",
			"content": (
				"请先调用搜索工具，再判断这个公司/组织名称对应的“最接近上级”组织。\n"
				"要求：\n"
				"1. 置信度用于体现不确定性，不要因为置信度低就直接把 parentOrgName 置空；\n"
				"2. 但如果你本来会填“无”“未知”“暂无”等占位内容，必须改成空字符串 \"\"；\n"
				"3. parentOrgName 必须是公司或组织名称，不要填写董事长、法定代表人、总经理、联系人等人名或职务；如果只能得到这类内容，也必须返回空字符串 \"\"；\n"
				"4. 如果来源里同时出现简称和全称，优先返回全称，不要返回简称；\n"
				f"输入名称：{org_name}"
			),
		},
	]

	source_index: dict[str, dict[str, str]] = {}
	tool_used = False

	for round_index in range(MAX_TOOL_ROUNDS):
		response = client.chat.completions.create(
			model=model_name,
			messages=messages,
			tools=_tool_schema(),
			tool_choice="auto",
		)
		choices = _get_value(response, "choices", None) or []
		if not choices:
			raise ParentOrgUpstreamError("parent_org_name upstream returned no choices")

		message = _get_value(choices[0], "message", None)
		if message is None:
			raise ParentOrgUpstreamError("parent_org_name upstream returned no message")

		tool_calls = _get_value(message, "tool_calls", None) or []
		if tool_calls:
			tool_used = True
			messages.append(_assistant_message_dict(message))
			for tool_call in tool_calls:
				function = _get_value(tool_call, "function", None)
				function_name = _get_value(function, "name", "")
				if function_name != "bocha_web_search":
					raise ParentOrgUpstreamError(f"parent_org_name upstream requested unsupported tool: {function_name}")

				arguments = _parse_tool_arguments(_get_value(function, "arguments", ""))
				query = arguments.get("query")
				if not isinstance(query, str) or not query.strip():
					raise ParentOrgUpstreamError("bocha_web_search query must be a non-empty string")

				results = _run_bocha_web_search(query)
				for item in results:
					source_index.setdefault(item["url"], {"title": item["title"], "url": item["url"]})

				messages.append(
					{
						"role": "tool",
						"tool_call_id": _get_value(tool_call, "id"),
						"content": json.dumps(_bocha_tool_payload(results), ensure_ascii=False),
					}
				)
			continue

		if not tool_used:
			raise ParentOrgUpstreamError("parent_org_name model did not call bocha_web_search")

		payload = _parse_json_object(_extract_message_content(message))
		parent_org_name, confidence, sources = _validate_payload(payload, source_index)
		logger.info(
			f"parent_org_name final orgName={org_name!r} route={route} model={model_name} "
			f"confidence={confidence} sources={len(sources)}"
		)
		return {
			"parentOrgName": parent_org_name,
			"confidence": confidence,
			"sources": sources,
			"route": route,
			"model": model_name,
		}

	raise ParentOrgUpstreamError(f"parent_org_name exceeded max tool rounds ({MAX_TOOL_ROUNDS})")


def resolve_parent_org_with_affiliate(org_name: str) -> dict[str, Any]:
	affiliate_org_name = resolve_affiliate_org_name(org_name)
	result = resolve_parent_org_name(affiliate_org_name)
	return {
		"affiliateOrgName": affiliate_org_name,
		"parentOrgName": result["parentOrgName"],
		"confidence": result["confidence"],
		"sources": result["sources"],
		"route": result["route"],
		"model": result["model"],
	}
