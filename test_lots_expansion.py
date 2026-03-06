import unittest

from src.concrete_product_table import (
    format_concrete_product_table_for_prompt,
    match_concrete_product_from_subject,
    normalize_concrete_product_name,
)
from src.custom_tools import compute_data_id, get_extract_prompt, normalize_field_value
from src.field_schemas import supplement_lot_products_from_candidates


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

    def test_normalize_item_lots_prompt_keeps_products_in_result_notice(self):
        prompt = get_extract_prompt("lots", fields_path="normalize_item_meta_flat_fields.yaml")
        self.assertIn("也必须同步输出对应的 lotProducts", prompt)
        self.assertIn("不能只输出 lotCandidates", prompt)

    def test_lots_prompt_matches_product_category_by_subjects_only(self):
        prompt = get_extract_prompt("lots", fields_path="normalize_item_meta_flat_fields.yaml")
        self.assertIn("只按 subjects", prompt)
        self.assertIn("不要使用 models/型号参与匹配", prompt)
        self.assertIn("平级候选项", prompt)
        self.assertIn("不表示首词优先", prompt)
        self.assertNotIn("每行第一个词", prompt)

    def test_concrete_product_table_prompt_treats_same_row_as_peer_candidates(self):
        prompt_table = format_concrete_product_table_for_prompt(
            "散装水泥运输车，粉粒物料车，干混砂浆背罐车，冷藏车"
        )
        self.assertEqual(
            prompt_table,
            "- 散装水泥运输车、粉粒物料车、干混砂浆背罐车、冷藏车",
        )
        self.assertNotIn(":", prompt_table)
        self.assertNotIn("：", prompt_table)

    def test_normalize_concrete_product_name_returns_matched_term_itself(self):
        self.assertEqual(normalize_concrete_product_name("粉粒物料车"), "粉粒物料车")

    def test_match_concrete_product_from_subject_returns_specific_term(self):
        self.assertEqual(
            match_concrete_product_from_subject("本次采购粉粒物料车 1 台"),
            "粉粒物料车",
        )


    def test_lot_candidates_infer_lot_number_from_lot_name(self):
        raw = [
            {
                "lotNumber": "",
                "lotName": "标6：主变冷却器包1：主变冷却器",
                "type": "中标",
                "candidates": "广西南宁贝旺电力设备有限公司",
            }
        ]

        out = normalize_field_value("lotCandidates", raw, "array")
        self.assertEqual(out[0]["lotNumber"], "标段六")

    def test_lot_products_infer_lot_number_and_subject_from_lot_name(self):
        raw = [
            {
                "lotNumber": "",
                "lotName": "16标包：混凝土输送泵",
                "subjects": "",
            }
        ]

        out = normalize_field_value("lotProducts", raw, "array")
        self.assertEqual(out[0]["lotNumber"], "标段十六")
        self.assertEqual(out[0]["subjects"], "混凝土输送泵")

    def test_supplement_lot_products_from_candidates(self):
        lot_products = [
            {
                "lotNumber": "",
                "lotName": "标8：昆明供电局检修试验中心升级改造及仪器设备购置包2：移动式悬臂起重机",
                "subjects": "移动式悬臂起重机",
            }
        ]
        lot_candidates = [
            {
                "lotNumber": "",
                "lotName": "标6：主变冷却器包1：主变冷却器",
                "type": "中标",
                "candidates": "广西南宁贝旺电力设备有限公司",
            }
        ]

        out = supplement_lot_products_from_candidates(lot_products, lot_candidates)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["lotNumber"], "标段八")
        self.assertEqual(out[1]["lotNumber"], "标段六")
        self.assertEqual(out[1]["subjects"], "主变冷却器")

if __name__ == "__main__":
    unittest.main()
