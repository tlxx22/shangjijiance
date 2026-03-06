import unittest

from src.estimated_amount_deriver import build_estimated_amount_source_text, fill_estimated_amount_after_lots


class TestEstimatedAmountDeriver(unittest.IsolatedAsyncioTestCase):
	async def test_winner_amount_no_extractor_call(self):
		calls = {"n": 0}

		async def stub_extractor(*_args, **_kwargs):
			calls["n"] += 1
			return {"estimatedAmount": "999~999"}

		item = {
			"winnerAmount": 123,
			"lotCandidates": [],
			"lotProducts": [{"subjects": "A"}],
			"estimatedAmount": "",
			"announcementName": "t",
			"announcementContent": "c",
		}
		await fill_estimated_amount_after_lots(
			item,
			site_name="test",
			fields_path="extract_fields.yaml",
			extractor=stub_extractor,
		)
		self.assertEqual(calls["n"], 0)
		self.assertEqual(item.get("estimatedAmount"), "123~123")

	async def test_candidate_price_no_extractor_call(self):
		calls = {"n": 0}

		async def stub_extractor(*_args, **_kwargs):
			calls["n"] += 1
			return {"estimatedAmount": "999~999"}

		item = {
			"winnerAmount": None,
			"lotCandidates": [{"type": "中标候选人", "candidatePrices": 456}],
			"lotProducts": [{"subjects": "A"}],
			"estimatedAmount": "",
			"announcementName": "t",
			"announcementContent": "c",
		}
		await fill_estimated_amount_after_lots(
			item,
			site_name="test",
			fields_path="extract_fields.yaml",
			extractor=stub_extractor,
		)
		self.assertEqual(calls["n"], 0)
		self.assertEqual(item.get("estimatedAmount"), "456~456")

	async def test_lot_products_trigger_estimation(self):
		calls = {"n": 0}
		captured = {"text": ""}

		async def stub_extractor(text, *_args, **_kwargs):
			calls["n"] += 1
			captured["text"] = text
			return {"estimatedAmount": "1000~2000"}

		item = {
			"winnerAmount": None,
			"lotCandidates": [],
			"lotProducts": [{"subjects": "装载机", "quantities": "1", "quantityUnit": "辆"}],
			"estimatedAmount": "",
			"announcementName": "装载机询价",
			"announcementContent": "采购装载机1辆。最高限价为120000元。联系人张三，联系电话123456。",
		}
		await fill_estimated_amount_after_lots(
			item,
			site_name="test",
			fields_path="extract_fields.yaml",
			extractor=stub_extractor,
		)
		self.assertEqual(calls["n"], 1)
		self.assertEqual(item.get("estimatedAmount"), "1000~2000")
		self.assertIn('"subjects": "装载机"', captured["text"])
		self.assertIn("最高限价为120000元", captured["text"])
		self.assertIn("联系电话123456", captured["text"])
		self.assertIn("其它正文内容请忽略", captured["text"])

	async def test_no_lot_products_no_extractor_call(self):
		calls = {"n": 0}

		async def stub_extractor(*_args, **_kwargs):
			calls["n"] += 1
			return {"estimatedAmount": "1000~2000"}

		item = {
			"winnerAmount": None,
			"lotCandidates": [],
			"lotProducts": [],
			"estimatedAmount": "",
			"announcementName": "t",
			"announcementContent": "c",
		}
		await fill_estimated_amount_after_lots(
			item,
			site_name="test",
			fields_path="extract_fields.yaml",
			extractor=stub_extractor,
		)
		self.assertEqual(calls["n"], 0)
		self.assertEqual(item.get("estimatedAmount"), "")

	def test_build_estimated_amount_source_text_keeps_body_excerpt_but_guides_llm_filtering(self):
		text = build_estimated_amount_source_text(
			lot_products=[{"subjects": "推土机", "quantities": "2", "quantityUnit": "台"}],
			announcement_content="本项目联系人李四。招标控制价为300000元，工期30天。",
		)
		self.assertIn('"subjects": "推土机"', text)
		self.assertIn("招标控制价为300000元", text)
		self.assertIn("联系人李四", text)
		self.assertIn("不要根据正文重新补标的物", text)
		self.assertIn("标的物信息只以 lotProducts 为准", text)
		self.assertIn("单价/数量/总价为 0 等明显占位值", text)
		self.assertIn("真实市场中的采购/成交价格", text)
		self.assertIn("不能为了满足格式随意给出 0、1", text)
		self.assertIn("会直接约束金额范围的价格边界信息", text)


if __name__ == "__main__":
	unittest.main()

