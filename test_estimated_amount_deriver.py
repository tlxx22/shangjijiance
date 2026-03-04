import unittest

from src.estimated_amount_deriver import fill_estimated_amount_after_lots


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

		async def stub_extractor(*_args, **_kwargs):
			calls["n"] += 1
			return {"estimatedAmount": "1000~2000"}

		item = {
			"winnerAmount": None,
			"lotCandidates": [],
			"lotProducts": [{"subjects": "装载机", "quantities": "1", "quantityUnit": "辆"}],
			"estimatedAmount": "",
			"announcementName": "装载机询价",
			"announcementContent": "采购装载机 1 辆。",
		}
		await fill_estimated_amount_after_lots(
			item,
			site_name="test",
			fields_path="extract_fields.yaml",
			extractor=stub_extractor,
		)
		self.assertEqual(calls["n"], 1)
		self.assertEqual(item.get("estimatedAmount"), "1000~2000")

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


if __name__ == "__main__":
	unittest.main()

