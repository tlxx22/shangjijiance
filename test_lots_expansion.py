import unittest

from src.custom_tools import compute_data_id, normalize_field_value


class TestLotsExpansion(unittest.TestCase):
	def test_lot_products_do_not_expand_by_separators(self):
		raw = [
			{
				"lotNumber": "标段一",
				"lotName": "",
				"subjects": "装载机",
				"productCategory": "小型轮式装载机",
				"models": "定载重量：3t；卸载高度＞3100mm；可选斗容：1.4~3m3",
				"unitPrices": None,
				"quantities": "1",
				"quantityUnit": "辆",
			}
		]

		out = normalize_field_value("lotProducts", raw, "array")
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["lotNumber"], "标段一")
		self.assertEqual(out[0]["subjects"], "装载机")
		self.assertEqual(out[0]["models"], "定载重量：3t；卸载高度＞3100mm；可选斗容：1.4~3m3")

	def test_lot_products_join_lists_not_expand(self):
		raw = [
			{
				"lotNumber": "标段一",
				"lotName": "包1",
				"subjects": ["A", "B"],
				"productCategory": ["C1", "C2"],
				"models": ["M1", "M2"],
				"unitPrices": ["280.00", "123.33"],
				"quantities": ["2", "3"],
				"quantityUnit": ["台", "套"],
			}
		]

		out = normalize_field_value("lotProducts", raw, "array")
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["subjects"], "A,B")
		self.assertEqual(out[0]["productCategory"], "C1,C2")
		self.assertEqual(out[0]["models"], "M1,M2")
		self.assertEqual(out[0]["unitPrices"], 280.0)
		self.assertEqual(out[0]["quantities"], "2")
		self.assertEqual(out[0]["quantityUnit"], "台,套")

	def test_lot_candidates_expand_rows(self):
		raw = [
			{
				"lotNumber": "标段一",
				"lotName": "包1",
				"type": "中标候选人",
				"candidates": ["A公司", "B公司", "C公司"],
				"candidatePrices": ["97.00", "98.50", "99.00"],
			}
		]

		out = normalize_field_value("lotCandidates", raw, "array")
		self.assertEqual(len(out), 3)
		self.assertTrue(all(x.get("type") == "中标候选人" for x in out))
		self.assertEqual(out[0]["candidates"], "A公司")
		self.assertEqual(out[1]["candidatePrices"], 98.5)
		self.assertNotIn("winner", out[0])
		self.assertNotIn("winningAmount", out[0])

	def test_lot_candidates_backward_compat_winner_only(self):
		raw = [
			{
				"lotNumber": "标段一",
				"lotName": "包1",
				"candidates": [],
				"candidatePrices": [],
				"winner": "A公司",
				"winningAmount": 97.0,
			}
		]

		out = normalize_field_value("lotCandidates", raw, "array")
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["type"], "中标")
		self.assertEqual(out[0]["candidates"], "A公司")
		self.assertEqual(out[0]["candidatePrices"], 97.0)

	def test_compute_data_id_stable(self):
		payload = {"b": 2, "a": 1}
		self.assertEqual(compute_data_id(payload), compute_data_id({"a": 1, "b": 2}))


if __name__ == "__main__":
	unittest.main()

