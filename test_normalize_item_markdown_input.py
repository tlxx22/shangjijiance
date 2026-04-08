import asyncio
import json
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient


class TestNormalizeItemMarkdownInput(unittest.TestCase):
	def test_structured_schema_name_max_len_64(self):
		from pathlib import Path

		from src.custom_tools import get_extract_fields
		from src.structured_schemas import build_extract_fields_model

		fields_path = "normalize_item_meta_flat_fields.yaml"
		stage = "estimated_amount"
		fields = get_extract_fields(stage, fields_path=fields_path)
		Schema = build_extract_fields_model(
			fields,
			model_name=f"ExtractFieldsText_{Path(fields_path).stem}_{stage}",
		)
		self.assertLessEqual(len(Schema.__name__), 64)

	def test_address_detail_prompt_no_longer_mentions_description(self):
		from src.custom_tools import get_extract_prompt

		prompt = get_extract_prompt("address_detail", fields_path="normalize_item_meta_flat_fields.yaml")
		self.assertNotIn("JSON + description", prompt)
		self.assertNotIn(" description ", f" {prompt} ")
		self.assertNotIn("以 description", prompt)

	def test_wrap_source_json_text_mode_keeps_markdown(self):
		md = "### 标题\n标题内容\n\n### 正文\n正文内容\n\n### 发布时间\n2026-02-16\n"

		p = subprocess.run(
			[
				sys.executable,
				"scripts/wrap_source_json.py",
				"--mode",
				"text",
			],
			input=md,
			text=True,
			encoding="utf-8",
			capture_output=True,
			check=True,
		)
		out = json.loads(p.stdout)
		self.assertEqual(out["sourceJson"].replace("\r\n", "\n"), md.strip())

	def test_split_primary_secondary_by_title_body_keywords(self):
		from src.custom_tools import _split_normalize_item_primary_secondary_text

		md = (
			"### 公告标题\n"
			"这里是标题\n\n"
			"### 公告正文\n"
			"这里是正文第一行\n这里是正文第二行\n\n"
			"### 公告类别\n"
			"中标\n\n"
			"### 其它字段\n"
			"可能不准\n"
		)

		primary, secondary = _split_normalize_item_primary_secondary_text(md)
		self.assertIn("【标题】\n这里是标题", primary)
		self.assertIn("【正文】\n这里是正文第一行\n这里是正文第二行", primary)
		self.assertIn("### 公告类别", secondary)
		self.assertIn("### 其它字段", secondary)
		self.assertNotIn("### 公告标题", secondary)
		self.assertNotIn("### 公告正文", secondary)

	def test_announcement_date_prefers_secondary_in_prompt(self):
		import asyncio
		from unittest.mock import patch

		from src.custom_tools import extract_fields_from_text

		captured: dict[str, object] = {}

		async def stub_ainvoke(messages, Schema):  # noqa: N802 - keep arg name aligned with caller
			captured["messages"] = messages
			return Schema()

		md = (
			"### 公告标题\n"
			"这里是标题\n\n"
			"### 公告正文\n"
			"正文里可能有多个日期：开标 2026-03-12，正文末尾 2026-03-03。\n\n"
			"### 发布时间\n"
			"2026-03-01\n"
		)

		with patch("src.custom_tools.ainvoke_structured", new=stub_ainvoke):
			asyncio.run(
				extract_fields_from_text(
					md,
					site_name="normalize_item",
					stage="meta",
					fields_path="normalize_item_meta_flat_fields.yaml",
				)
			)

		messages = captured.get("messages") or []
		self.assertEqual(len(messages), 2)
		system_prompt = messages[0]["content"]
		user_prompt = messages[1]["content"]
		self.assertIn("Exception (announcementDate): prefer SECONDARY_TEXT", system_prompt)
		self.assertIn("PRIMARY_TEXT:", user_prompt)
		self.assertIn("SECONDARY_TEXT:", user_prompt)

	def _disabled_test_split_exact_body_section_for_direct_assignment(self):
		from src.custom_tools import _split_normalize_item_body_section

		md = (
			"### 标题\n"
			"这里是标题\n\n"
			"### 正文\n"
			"这里是正文第一行\n这里是正文第二行\n\n"
			"### 发布时间\n"
			"2026-03-01\n"
		)

		body, remaining = _split_normalize_item_body_section(md)
		self.assertEqual(body, "这里是正文第一行\n这里是正文第二行")
		self.assertIn("### 标题", remaining)
		self.assertIn("### 发布时间", remaining)
		self.assertNotIn("### 正文", remaining)
		self.assertNotIn("这里是正文第一行\n这里是正文第二行", remaining)

	def _disabled_test_normalize_item_graph_assigns_body_directly_and_strips_meta_input(self):
		import asyncio

		from src.normalize_item_graph import run_normalize_item_core_graph

		captured: dict[str, str] = {}

		async def fake_extract(src_text, *, stage, product_category_table):  # noqa: ANN001
			captured[stage] = src_text
			if stage == "meta":
				return {
					"announcementName": "这里是标题",
					"announcementContent": "",
					"announcementType": "招标",
				}
			if stage == "lots":
				return {"lotProducts": [], "lotCandidates": []}
			return {}

		async def fake_fill_product_categories(lot_products, *, site_name, product_category_table):  # noqa: ANN001
			return lot_products or []

		async def fake_fill_estimated_amount(item, *, site_name, fields_path):  # noqa: ANN001
			return None

		md = (
			"### 标题\n"
			"这里是标题\n\n"
			"### 正文\n"
			"这里是正文第一行\n这里是正文第二行\n\n"
			"### 发布时间\n"
			"2026-03-01\n"
		)

		with patch("src.normalize_item_graph._extract_normalize_item_fields", new=fake_extract):
			with patch("src.normalize_item_graph.fill_product_categories_after_lots", new=fake_fill_product_categories):
				with patch("src.normalize_item_graph.fill_estimated_amount_after_lots", new=fake_fill_estimated_amount):
					item = asyncio.run(run_normalize_item_core_graph(md))

		self.assertEqual(item["announcementContent"], "这里是正文第一行\n这里是正文第二行")
		self.assertNotIn("### 正文", captured["meta"])
		self.assertIn("### 正文", captured["lots"])

	def test_prepare_normalize_item_source_json_with_cleaned_body(self):
		from src.custom_tools import _prepare_normalize_item_source_json_with_cleaned_body

		md = (
			"### 标题\n"
			"这里是标题\n\n"
			"### 正文\n"
			"<div style=\"color:red\"><p>正文内容</p><script>alert(1)</script></div>\n\n"
			"### 发布时间\n"
			"2026-03-01\n"
		)

		body, llm_source_json = _prepare_normalize_item_source_json_with_cleaned_body(
			md,
			site_name="normalize_item",
		)
		self.assertIn("<p>正文内容</p>", body)
		self.assertNotIn("<script>", body)
		self.assertIn("### 标题", llm_source_json)
		self.assertIn("### 正文", llm_source_json)
		self.assertIn("### 发布时间", llm_source_json)
		self.assertIn("<p>正文内容</p>", llm_source_json)
		self.assertNotIn("<script>", llm_source_json)

	def test_normalize_item_graph_assigns_cleaned_body_directly_and_keeps_body_for_llm(self):
		import asyncio

		from src.normalize_item_graph import run_normalize_item_core_graph

		captured: dict[str, str] = {}

		async def fake_extract(src_text, *, stage, product_category_table):  # noqa: ANN001
			captured[stage] = src_text
			if stage == "meta":
				return {
					"announcementName": "这里是标题",
					"announcementContent": "LLM正文",
					"announcementType": "招标",
				}
			if stage == "lots":
				return {"lotProducts": [], "lotCandidates": []}
			return {}

		async def fake_fill_product_categories(lot_products, *, site_name, product_category_table):  # noqa: ANN001
			return lot_products or []

		async def fake_fill_estimated_amount(item, *, site_name, fields_path):  # noqa: ANN001
			return None

		md = (
			"### 标题\n"
			"这里是标题\n\n"
			"### 正文\n"
			"<div style=\"color:red\"><p>正文内容</p><script>alert(1)</script></div>\n\n"
			"### 发布时间\n"
			"2026-03-01\n"
		)

		with patch("src.normalize_item_graph._extract_normalize_item_fields", new=fake_extract):
			with patch("src.normalize_item_graph.fill_product_categories_after_lots", new=fake_fill_product_categories):
				with patch("src.normalize_item_graph.fill_estimated_amount_after_lots", new=fake_fill_estimated_amount):
					item = asyncio.run(run_normalize_item_core_graph(md))

		self.assertIn("<p>正文内容</p>", item["announcementContent"])
		self.assertNotIn("<script>", item["announcementContent"])
		self.assertIn("### 正文", captured["meta"])
		self.assertIn("<p>正文内容</p>", captured["meta"])
		self.assertNotIn("<script>", captured["meta"])
		self.assertIn("### 正文", captured["lots"])

	def test_try_normalize_announcement_type_prefers_qna_for_clarification_keywords(self):
		from src.field_schemas import try_normalize_announcement_type

		self.assertEqual(try_normalize_announcement_type("招标文件澄清公告"), "答疑")
		self.assertEqual(try_normalize_announcement_type("关于某项目的澄清文件"), "答疑")
		self.assertEqual(try_normalize_announcement_type("疑问回复"), "答疑")
		self.assertEqual(try_normalize_announcement_type("招标文件澄清/变更公告"), "答疑")

	def test_announcement_type_prompt_marks_clarification_as_qna(self):
		from src.custom_tools import get_extract_prompt

		prompt = get_extract_prompt("meta", fields_path="normalize_item_meta_flat_fields.yaml")
		self.assertIn("澄清公告/澄清文件/澄清通知/答疑公告/疑问回复/问题答复", prompt)
		self.assertIn("优先判为“答疑”", prompt)

	def test_estimated_amount_prompt_only_uses_body_for_price_bounds(self):
		import asyncio
		from unittest.mock import patch

		from src.custom_tools import extract_fields_from_text

		captured: dict[str, object] = {}

		async def stub_ainvoke(messages, Schema):  # noqa: N802 - keep arg name aligned with caller
			captured["messages"] = messages
			return Schema()

		md = (
			"### 标题\n"
			"矿用地下自卸车采购项目\n\n"
			"### 正文\n"
			"正文里有设备名，也有最高限价189.3万元。\n\n"
			"### 标的物\n"
			"物资名称：矿用地下自卸车 单价：0 数量：0 总价：0\n"
		)

		with patch("src.custom_tools.ainvoke_structured", new=stub_ainvoke):
			asyncio.run(
				extract_fields_from_text(
					md,
					site_name="normalize_item",
					stage="estimated_amount",
					fields_path="normalize_item_meta_flat_fields.yaml",
				)
			)

		messages = captured.get("messages") or []
		self.assertEqual(len(messages), 2)
		system_prompt = messages[0]["content"]
		self.assertIn("ONLY source of item identity/scope/specs/quantities", system_prompt)
		self.assertIn("Do NOT reconstruct, add, split, or rewrite procurement items from the title/body text", system_prompt)
		self.assertIn("Body/title text may be used ONLY to identify explicit price-bound constraints", system_prompt)
		self.assertIn("unit price = 0, quantity = 0, or total = 0", system_prompt)
		self.assertIn("realistic real-world procurement / transaction prices", system_prompt)
		self.assertIn("0, 1, or other tiny placeholder values are invalid", system_prompt)

	def test_is_equipment_default_true_without_llm(self):
		import asyncio

		from src.custom_tools import extract_fields_from_text

		got = asyncio.run(
			extract_fields_from_text(
				"",
				site_name="normalize_item",
				stage="meta",
				fields_path="normalize_item_meta_flat_fields.yaml",
			)
		)
		self.assertIn("isEquipment", got)
		self.assertTrue(got["isEquipment"])

	def test_structured_schema_default_is_equipment_true(self):
		from src.custom_tools import get_extract_fields
		from src.structured_schemas import build_extract_fields_model

		fields = get_extract_fields("meta", fields_path="normalize_item_meta_flat_fields.yaml")
		Schema = build_extract_fields_model(fields, model_name="TestSchema_isEquipmentDefault")
		obj = Schema()
		self.assertTrue(getattr(obj, "isEquipment", False))

	def test_normalize_item_empty_input_sets_is_equipment_true(self):
		import asyncio

		from src.llm_transform import normalize_source_json_to_item

		item = asyncio.run(normalize_source_json_to_item(""))
		self.assertIn("isEquipment", item)
		self.assertTrue(item["isEquipment"])

	def test_crawl_extract_fields_has_is_equipment(self):
		from src.config_manager import load_extract_fields

		meta_fields = load_extract_fields(stage="meta")
		hits = [f for f in meta_fields if getattr(f, "key", "") == "isEquipment"]
		self.assertEqual(len(hits), 1)
		self.assertEqual(hits[0].type, "boolean")

	def test_is_equipment_prompt_contains_hard_exclusions(self):
		from src.custom_tools import get_extract_prompt

		prompt = get_extract_prompt("meta", fields_path="normalize_item_meta_flat_fields.yaml")
		self.assertIn("最高优先级排除规则", prompt)
		self.assertIn("二手设备采购", prompt)
		self.assertIn("招标代理服务", prompt)
		self.assertIn("设备安装", prompt)
		self.assertIn("稳定土搅拌站安装鲁班二次寻源", prompt)
		self.assertIn("维修", prompt)
		self.assertIn("交流变频电牵引采煤机维修结果公告", prompt)
		self.assertIn("海运费", prompt)
		self.assertIn("柴油正面吊海运费项目", prompt)
		self.assertIn("施工服务", prompt)
		self.assertIn("工程-施工", prompt)
		self.assertIn("2026年杨河乡草产业综合加工项目", prompt)


def _fake_parent_org_response(
	*,
	output_text: str,
	annotations: list[object] | None = None,
	search_sources: list[object] | None = None,
	response_id: str = "resp_test",
):
	return SimpleNamespace(
		id=response_id,
		output_text=output_text,
		output=[
			SimpleNamespace(
				type="message",
				content=[
					SimpleNamespace(
						type="output_text",
						text=output_text,
						annotations=list(annotations or []),
					)
				],
			),
			SimpleNamespace(
				type="web_search_call",
				action=SimpleNamespace(
					type="search",
					sources=list(search_sources or []),
				),
			),
		],
	)


class _FakeResponsesClient:
	def __init__(self, response):
		self._response = response

	def create(self, **kwargs):
		return self._response


class _FakeOpenAIClient:
	def __init__(self, response):
		self.responses = _FakeResponsesClient(response)


class TestParentOrgName(unittest.TestCase):
	def test_resolve_parent_org_name_prefers_annotations_and_preserves_raw_value(self):
		from src.parent_org_service import resolve_parent_org_name

		response = _fake_parent_org_response(
			output_text='{"parentOrgName":" 中国化学工程第三建设有限公司 ","confidence":0.82}',
			annotations=[
				SimpleNamespace(type="url_citation", title="来源一", url="https://a.example"),
				SimpleNamespace(type="url_citation", title="来源一重复", url="https://a.example"),
				SimpleNamespace(type="url_citation", title="来源二", url="https://b.example"),
			],
			search_sources=[SimpleNamespace(url="https://fallback.example")],
		)

		with patch("src.parent_org_service.trans.ROUTE", "openai"), \
			patch.dict(
				"src.parent_org_service.os.environ",
				{"OPENAI_API_KEY": "test-key", "OPENAI_BASE_URL": "https://example.com", "OPENAI_MODEL": "demo-model"},
				clear=False,
			), \
			patch("src.parent_org_service.OpenAI", return_value=_FakeOpenAIClient(response)):
			got = resolve_parent_org_name("中国化学工程第三建设有限公司山东分公司")

		self.assertEqual(got["parentOrgName"], " 中国化学工程第三建设有限公司 ")
		self.assertEqual(got["confidence"], 0.82)
		self.assertEqual(
			got["sources"],
			[
				{"title": "来源一", "url": "https://a.example"},
				{"title": "来源二", "url": "https://b.example"},
			],
		)

	def test_resolve_parent_org_name_falls_back_to_search_call_sources(self):
		from src.parent_org_service import resolve_parent_org_name

		response = _fake_parent_org_response(
			output_text='{"parentOrgName":"中国化学工程第三建设有限公司","confidence":0.66}',
			search_sources=[
				SimpleNamespace(url="https://a.example"),
				SimpleNamespace(url="https://a.example"),
				SimpleNamespace(url="https://b.example"),
			],
		)

		with patch("src.parent_org_service.trans.ROUTE", "openai"), \
			patch.dict(
				"src.parent_org_service.os.environ",
				{"OPENAI_API_KEY": "test-key", "OPENAI_BASE_URL": "https://example.com", "OPENAI_MODEL": "demo-model"},
				clear=False,
			), \
			patch("src.parent_org_service.OpenAI", return_value=_FakeOpenAIClient(response)):
			got = resolve_parent_org_name("中国化学工程第三建设有限公司山东分公司")

		self.assertEqual(
			got["sources"],
			[
				{"title": "", "url": "https://a.example"},
				{"title": "", "url": "https://b.example"},
			],
		)

	def test_resolve_parent_org_name_rejects_invalid_confidence(self):
		from src.parent_org_service import ParentOrgUpstreamError, resolve_parent_org_name

		response = _fake_parent_org_response(
			output_text='{"parentOrgName":"中国化学工程第三建设有限公司","confidence":1.5}',
		)

		with patch("src.parent_org_service.trans.ROUTE", "openai"), \
			patch.dict(
				"src.parent_org_service.os.environ",
				{"OPENAI_API_KEY": "test-key", "OPENAI_BASE_URL": "https://example.com", "OPENAI_MODEL": "demo-model"},
				clear=False,
			), \
			patch("src.parent_org_service.OpenAI", return_value=_FakeOpenAIClient(response)):
			with self.assertRaises(ParentOrgUpstreamError):
				resolve_parent_org_name("中国化学工程第三建设有限公司")

	def test_parent_org_name_endpoint_success(self):
		from app import app

		with TestClient(app) as client, patch(
			"app.resolve_parent_org_name",
			return_value={
				"parentOrgName": "中国化学工程第三建设有限公司",
				"confidence": 0.82,
				"sources": [{"title": "来源一", "url": "https://a.example"}],
				"route": "openai",
				"model": "demo-model",
				"response_id": "resp_1",
			},
		):
			resp = client.post(
				"/parent_org_name",
				json={"orgName": "中国化学工程第三建设有限公司山东分公司"},
			)

		self.assertEqual(resp.status_code, 200)
		self.assertEqual(
			resp.json(),
			{
				"parentOrgName": "中国化学工程第三建设有限公司",
				"confidence": 0.82,
				"sources": [{"title": "来源一", "url": "https://a.example"}],
			},
		)

	def test_parent_org_name_endpoint_returns_500_for_route_error(self):
		from app import app

		with TestClient(app) as client, patch("app.resolve_parent_org_name", side_effect=RuntimeError("unsupported route")):
			resp = client.post("/parent_org_name", json={"orgName": "中国化学工程第三建设有限公司"})

		self.assertEqual(resp.status_code, 500)
		self.assertIn("unsupported route", resp.text)

	def test_parent_org_name_endpoint_returns_400_for_invalid_body(self):
		from app import app

		with TestClient(app) as client:
			resp = client.post("/parent_org_name", json={"orgName": ""})

		self.assertEqual(resp.status_code, 400)


class TestInputTruncated(unittest.TestCase):
	def test_extract_fields_from_text_marks_truncation_when_over_cap(self):
		from src.custom_tools import extract_fields_from_text

		async def stub_ainvoke(messages, Schema):  # noqa: N802
			return Schema()

		text = "a" * 300001
		with patch("src.custom_tools.ainvoke_structured", new=stub_ainvoke):
			got = asyncio.run(
				extract_fields_from_text(
					text,
					site_name="normalize_item",
					stage="meta",
					fields_path="normalize_item_meta_flat_fields.yaml",
				)
			)

		self.assertTrue(got["__inputTruncated__"])

	def test_extract_fields_from_text_marks_no_truncation_when_under_cap(self):
		from src.custom_tools import extract_fields_from_text

		async def stub_ainvoke(messages, Schema):  # noqa: N802
			return Schema()

		with patch("src.custom_tools.ainvoke_structured", new=stub_ainvoke):
			got = asyncio.run(
				extract_fields_from_text(
					"short text",
					site_name="normalize_item",
					stage="meta",
					fields_path="normalize_item_meta_flat_fields.yaml",
				)
			)

		self.assertFalse(got["__inputTruncated__"])

	def test_extract_fields_from_html_marks_truncation_when_over_cap(self):
		from src.custom_tools import extract_fields_from_html

		async def stub_ainvoke(messages, Schema):  # noqa: N802
			return Schema()

		html = "<div>" + ("a" * 200001) + "</div>"
		with patch("src.custom_tools.ainvoke_structured", new=stub_ainvoke):
			got = asyncio.run(
				extract_fields_from_html(
					html,
					site_name="test",
					stage="contacts",
				)
			)

		self.assertTrue(got["__inputTruncated__"])

	def test_compute_data_id_ignores_input_truncated(self):
		from src.custom_tools import compute_data_id

		payload_false = {
			"version": 1,
			"dataId": "",
			"announcementName": "test",
			"inputTruncated": False,
		}
		payload_true = dict(payload_false)
		payload_true["inputTruncated"] = True

		self.assertEqual(compute_data_id(payload_false), compute_data_id(payload_true))

	def test_normalize_item_graph_aggregates_input_truncated(self):
		from src.normalize_item_graph import run_normalize_item_core_graph

		async def fake_extract(src_text, *, stage, product_category_table):  # noqa: ANN001
			if stage == "meta":
				return {
					"announcementName": "标题",
					"announcementContent": "LLM正文",
					"announcementType": "招标",
					"__inputTruncated__": True,
				}
			if stage == "contacts":
				return {"buyerName": "采购单位", "__inputTruncated__": False}
			if stage == "address_detail":
				return {"buyerAddressDetail": "", "__inputTruncated__": False}
			if stage == "lots":
				return {"lotProducts": [], "lotCandidates": [], "__inputTruncated__": False}
			return {"__inputTruncated__": False}

		async def fake_fill_product_categories(lot_products, *, site_name, product_category_table):  # noqa: ANN001
			return lot_products or []

		async def fake_fill_estimated_amount(item, *, site_name, fields_path):  # noqa: ANN001
			return None

		md = (
			"### 标题\n"
			"这里是标题\n\n"
			"### 正文\n"
			"<div><p>正文内容</p></div>\n\n"
			"### 发布时间\n"
			"2026-03-01\n"
		)

		with patch("src.normalize_item_graph._extract_normalize_item_fields", new=fake_extract):
			with patch("src.normalize_item_graph.fill_product_categories_after_lots", new=fake_fill_product_categories):
				with patch("src.normalize_item_graph.fill_estimated_amount_after_lots", new=fake_fill_estimated_amount):
					item = asyncio.run(run_normalize_item_core_graph(md))

		self.assertTrue(item["inputTruncated"])
		self.assertIn("<p>正文内容</p>", item["announcementContent"])

	def test_crawl_extract_stage_consumes_internal_truncated_flag(self):
		from src.crawl_detail_graph import _extract_contacts

		async def fake_extract_fields_from_html(*args, **kwargs):  # noqa: ANN001
			return {"buyerName": "采购单位", "__inputTruncated__": True}

		with patch("src.crawl_detail_graph.extract_fields_from_html", new=fake_extract_fields_from_html):
			extracted = asyncio.run(
				_extract_contacts(
					{
						"announcement_content": "<div>正文</div>",
						"site_name": "test",
					}
				)
			)

		self.assertTrue(extracted["contacts_input_truncated"])
		self.assertEqual(extracted["contacts_fields"]["buyerName"], "采购单位")
		self.assertNotIn("__inputTruncated__", extracted["contacts_fields"])

	def test_crawl_merge_result_data_aggregates_input_truncated(self):
		from src.crawl_detail_graph import _merge_result_data

		state = {
			"title": "测试标题",
			"detail_url": "https://example.com/detail",
			"announcement_content": "<div>正文</div>",
			"meta_fields": {"announcementType": "招标"},
			"contacts_fields": {},
			"address_detail_fields": {},
			"lot_products": [],
			"lot_candidates": [],
			"meta_input_truncated": False,
			"contacts_input_truncated": True,
			"address_detail_input_truncated": False,
			"lots_input_truncated": False,
		}

		got = _merge_result_data(state)
		self.assertTrue(got["result_data"]["inputTruncated"])


if __name__ == "__main__":
	unittest.main()

