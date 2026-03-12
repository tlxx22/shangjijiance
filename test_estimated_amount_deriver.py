import unittest

from src.estimated_amount_deriver import (
    MAX_ESTIMATED_AMOUNT_RETRIES,
    _extract_estimated_amount_candidate_output,
    build_estimated_amount_source_text,
    fill_estimated_amount_after_lots,
)


class TestEstimatedAmountDeriver(unittest.IsolatedAsyncioTestCase):
    async def test_existing_valid_range_skips_extractor(self):
        calls = {"n": 0}

        async def stub_extractor(*_args, **_kwargs):
            calls["n"] += 1
            return {"estimatedAmount": "999~999"}

        item = {
            "winnerAmount": None,
            "lotCandidates": [],
            "lotProducts": [{"subjects": "loader"}],
            "estimatedAmount": "100  ~  200",
            "announcementContent": "buy 1 loader",
        }
        await fill_estimated_amount_after_lots(
            item,
            site_name="test",
            fields_path="extract_fields.yaml",
            extractor=stub_extractor,
        )
        self.assertEqual(calls["n"], 0)
        self.assertEqual(item.get("estimatedAmount"), "100  ~  200")

    async def test_retries_until_valid_range_with_plain_text_output(self):
        calls = {"n": 0}
        captured = {"texts": []}
        outputs = ["about 100k", "100000 ~ 120000"]

        async def stub_extractor(text, *_args, **_kwargs):
            captured["texts"].append(text)
            index = calls["n"]
            calls["n"] += 1
            return outputs[index]

        item = {
            "winnerAmount": None,
            "lotCandidates": [],
            "lotProducts": [{"subjects": "wheel loader", "quantities": 1}],
            "estimatedAmount": "",
            "announcementContent": "buy 1 wheel loader, max price 120000 yuan",
        }
        await fill_estimated_amount_after_lots(
            item,
            site_name="test",
            fields_path="extract_fields.yaml",
            extractor=stub_extractor,
        )
        self.assertEqual(calls["n"], 2)
        self.assertEqual(item.get("estimatedAmount"), "100000 ~ 120000")
        self.assertIn("Previous estimatedAmount output was invalid", captured["texts"][1])

    async def test_retry_limit_falls_back_to_first_raw_output(self):
        calls = {"n": 0}

        async def stub_extractor(*_args, **_kwargs):
            calls["n"] += 1
            return "about 100k"

        item = {
            "winnerAmount": 123456,
            "lotCandidates": [],
            "lotProducts": [],
            "estimatedAmount": "",
            "announcementContent": "winning amount 123456 yuan",
        }
        await fill_estimated_amount_after_lots(
            item,
            site_name="test",
            fields_path="extract_fields.yaml",
            extractor=stub_extractor,
        )
        self.assertEqual(calls["n"], MAX_ESTIMATED_AMOUNT_RETRIES)
        self.assertEqual(item.get("estimatedAmount"), "about 100k")

    async def test_no_structured_clue_skips_extractor(self):
        calls = {"n": 0}

        async def stub_extractor(*_args, **_kwargs):
            calls["n"] += 1
            return "1000~2000"

        item = {
            "winnerAmount": None,
            "lotCandidates": [],
            "lotProducts": [],
            "estimatedAmount": "",
            "announcementContent": "contact only",
        }
        await fill_estimated_amount_after_lots(
            item,
            site_name="test",
            fields_path="extract_fields.yaml",
            extractor=stub_extractor,
        )
        self.assertEqual(calls["n"], 0)
        self.assertEqual(item.get("estimatedAmount"), "")

    def test_build_estimated_amount_source_text_contains_priority_and_retry_feedback(self):
        text = build_estimated_amount_source_text(
            lot_products=[{"subjects": "bulldozer", "quantities": 2, "quantityUnit": "units"}],
            announcement_content="control price 300000 yuan, contact Li Si, phone 123456",
            priority_amount=123456,
            current_estimated_amount="about 100k",
            previous_invalid_output="around 100-120k",
        )
        self.assertIn("Priority amount clues (JSON)", text)
        self.assertIn("123456", text)
        self.assertIn('"subjects": "bulldozer"', text)
        self.assertIn("control price 300000 yuan", text)
        self.assertIn("Previous estimatedAmount output was invalid", text)
        self.assertIn("you still must estimate a conservative total project range", text)

    def test_extract_estimated_amount_candidate_output_supports_dict_and_text(self):
        self.assertEqual(_extract_estimated_amount_candidate_output({"estimatedAmount": "1~2"}), "1~2")
        self.assertEqual(_extract_estimated_amount_candidate_output("3~4"), "3~4")
        self.assertEqual(_extract_estimated_amount_candidate_output(None), "")


if __name__ == "__main__":
    unittest.main()
