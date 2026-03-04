import json
import subprocess
import sys
import unittest


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


if __name__ == "__main__":
	unittest.main()
