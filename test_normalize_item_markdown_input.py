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


if __name__ == "__main__":
	unittest.main()

