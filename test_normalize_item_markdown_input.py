import json
import subprocess
import sys
import unittest


class TestNormalizeItemMarkdownInput(unittest.TestCase):
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


if __name__ == "__main__":
	unittest.main()
