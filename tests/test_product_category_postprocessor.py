import unittest
from unittest.mock import AsyncMock, patch

from src.product_category_postprocessor import (
	ProductCategorySelection,
	fill_product_categories_after_lots,
)


class ProductCategoryPostprocessorTests(unittest.IsolatedAsyncioTestCase):
	async def test_exact_match_priority_bypasses_llm(self):
		lot_products = [
			{
				"lotNumber": "标段一",
				"lotName": "",
				"subjects": "电动单梁起重机",
				"productCategory": "",
				"models": "电动单梁起重机（10t）",
				"unitPrices": None,
				"quantities": 2,
				"quantityUnit": "台",
			}
		]
		table = "门式回转起重机，电动单梁起重机，桥式起重机"

		with patch("src.product_category_postprocessor.ainvoke_structured", new_callable=AsyncMock) as mock_llm:
			rows = await fill_product_categories_after_lots(
				lot_products,
				site_name="test",
				product_category_table=table,
			)

		self.assertEqual(rows[0]["productCategory"], "电动单梁起重机")
		mock_llm.assert_not_called()

	async def test_prompt_explicitly_forbids_picking_first_term_when_exact_match_exists(self):
		lot_products = [
			{
				"lotNumber": "标段一",
				"lotName": "",
				"subjects": "厂房吊车",
				"productCategory": "",
				"models": "",
				"unitPrices": None,
				"quantities": "",
				"quantityUnit": "",
			}
		]
		table = "门式回转起重机，电动单梁起重机，桥式起重机"
		captured_messages: list[dict] = []

		async def fake_ainvoke_structured(messages, schema):
			captured_messages.extend(messages)
			return ProductCategorySelection(productCategory="桥式起重机")

		with patch("src.product_category_postprocessor.ainvoke_structured", side_effect=fake_ainvoke_structured):
			rows = await fill_product_categories_after_lots(
				lot_products,
				site_name="test",
				product_category_table=table,
			)

		self.assertEqual(rows[0]["productCategory"], "桥式起重机")
		system_prompt = captured_messages[0]["content"]
		self.assertIn("If `subjects` exactly matches a candidate term, you MUST return that exact candidate term.", system_prompt)
		self.assertIn("Never mechanically choose the first term in a row", system_prompt)
		self.assertIn("电动单梁起重机", system_prompt)


if __name__ == "__main__":
	unittest.main()
