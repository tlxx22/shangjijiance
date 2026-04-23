import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch


class TestIsOverseasProject(unittest.TestCase):
	def test_full_item_template_includes_flag_with_false_default(self):
		from src.llm_transform import _build_full_item_template

		item = _build_full_item_template()

		self.assertIn("isOverseasProject", item)
		self.assertFalse(item["isOverseasProject"])
		self.assertTrue(item["isEquipment"])

	def test_meta_schema_defaults_flag_to_false(self):
		from src.custom_tools import get_extract_fields
		from src.structured_schemas import build_extract_fields_model

		fields_path = "normalize_item_meta_flat_fields.yaml"
		fields = get_extract_fields("meta", fields_path=fields_path)
		Schema = build_extract_fields_model(
			fields,
			model_name=f"ExtractFieldsText_{Path(fields_path).stem}_meta",
		)

		obj = Schema()
		self.assertFalse(obj.isOverseasProject)
		self.assertTrue(obj.isEquipment)

	def test_normalize_item_text_prompt_includes_overseas_rule(self):
		from src.custom_tools import extract_fields_from_text

		captured: dict[str, object] = {}

		async def stub_ainvoke(messages, Schema):  # noqa: N802
			captured["messages"] = messages
			return Schema()

		md = (
			"### 标题\n"
			"境外矿区设备采购项目\n\n"
			"### 正文\n"
			"项目实施地点为境外矿区。\n\n"
			"### 发布时间\n"
			"2026-04-23\n"
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
		self.assertIn("Special rule for isOverseasProject", system_prompt)
		self.assertIn("China includes mainland China, Hong Kong, Macau, and Taiwan", system_prompt)
		self.assertIn("PRIMARY_TEXT:", user_prompt)

	def test_crawl_html_prompt_includes_overseas_rule(self):
		from src.custom_tools import extract_fields_from_html

		captured: dict[str, object] = {}

		async def stub_ainvoke(messages, Schema):  # noqa: N802
			captured["messages"] = messages
			return Schema()

		html = "<div><p>项目交付地为境外矿区。</p></div>"

		with patch("src.custom_tools.ainvoke_structured", new=stub_ainvoke):
			asyncio.run(
				extract_fields_from_html(
					html,
					site_name="unit_test_site",
					stage="meta",
				)
			)

		messages = captured.get("messages") or []
		self.assertEqual(len(messages), 2)
		system_prompt = messages[0]["content"]
		self.assertIn("Special rule for isOverseasProject", system_prompt)
		self.assertIn("execution / construction / use / delivery / service location is outside China", system_prompt)

	def test_crawl_merge_result_keeps_overseas_flag(self):
		from src.crawl_detail_graph import _merge_result_data

		state = {
			"title": "境外项目采购公告",
			"detail_url": "https://example.com/detail",
			"announcement_content": "<div>正文</div>",
			"meta_fields": {"isOverseasProject": True},
			"contacts_fields": {},
			"address_detail_fields": {},
			"lot_products": [],
			"lot_candidates": [],
			"meta_input_truncated": False,
			"contacts_input_truncated": False,
			"address_detail_input_truncated": False,
			"lots_input_truncated": False,
		}

		result = _merge_result_data(state)
		self.assertTrue(result["result_data"]["isOverseasProject"])


if __name__ == "__main__":
	unittest.main()
