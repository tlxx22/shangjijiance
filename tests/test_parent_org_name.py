import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import app as app_module
from src.parent_org_service import (
    _validate_payload,
    resolve_affiliate_org_name,
    resolve_parent_org_with_affiliate,
)


def _fake_client_with_message(content: str):
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=Mock(return_value={"choices": [{"message": {"content": content}}]})
            )
        )
    )


class ResolveAffiliateOrgNameTests(unittest.TestCase):
    def test_resolve_affiliate_org_name_uses_llm_json_result(self):
        client = _fake_client_with_message('{"affiliateOrgName": "中国化学工程第三建设有限公司"}')

        with patch("src.parent_org_service._get_client_config", return_value=("openai", client, "gpt-5.2")):
            result = resolve_affiliate_org_name("中国化学工程第三建设有限公司采购部")

        self.assertEqual(result, "中国化学工程第三建设有限公司")

    def test_resolve_affiliate_org_name_falls_back_to_original_on_invalid_output(self):
        client = _fake_client_with_message('{"affiliateOrgName": ""}')

        with patch("src.parent_org_service._get_client_config", return_value=("openai", client, "gpt-5.2")):
            result = resolve_affiliate_org_name("某某采购部")

        self.assertEqual(result, "某某采购部")


class ResolveParentOrgWithAffiliateTests(unittest.TestCase):
    def test_wrapper_uses_affiliate_name_for_parent_lookup(self):
        with patch("src.parent_org_service.resolve_affiliate_org_name", return_value="中交二航局第二工程有限公司") as mock_affiliate:
            with patch(
                "src.parent_org_service.resolve_parent_org_name",
                return_value={
                    "parentOrgName": "中交第二航务工程局有限公司",
                    "confidence": 0.91,
                    "sources": [{"title": "官网", "url": "https://example.com"}],
                    "route": "openai",
                    "model": "gpt-5.2",
                },
            ) as mock_parent:
                result = resolve_parent_org_with_affiliate("中交二航局第二工程有限公司采购部")

        mock_affiliate.assert_called_once_with("中交二航局第二工程有限公司采购部")
        mock_parent.assert_called_once_with("中交二航局第二工程有限公司")
        self.assertEqual(result["affiliateOrgName"], "中交二航局第二工程有限公司")
        self.assertEqual(result["parentOrgName"], "中交第二航务工程局有限公司")


class ParentOrgNameSourceFallbackTests(unittest.TestCase):
    def test_validate_payload_returns_placeholder_when_source_urls_do_not_match(self):
        payload = {
            "parentOrgName": "中国化学工程第三建设有限公司",
            "confidence": 0.82,
            "sourceUrls": ["https://not-in-search-results.example.com/detail"],
        }

        parent_org_name, confidence, sources = _validate_payload(payload, source_index={})

        self.assertEqual(parent_org_name, "中国化学工程第三建设有限公司")
        self.assertEqual(confidence, 0.82)
        self.assertEqual(sources, [{"title": "匹配失败", "url": "匹配失败"}])

    def test_validate_payload_keeps_real_sources_when_urls_match(self):
        payload = {
            "parentOrgName": "中国化学工程第三建设有限公司",
            "confidence": 0.82,
            "sourceUrls": ["https://example.com/a"],
        }
        source_index = {
            "https://example.com/a": {
                "title": "中国化学工程第三建设有限公司 - 官网",
                "url": "https://example.com/a",
            }
        }

        parent_org_name, confidence, sources = _validate_payload(payload, source_index=source_index)

        self.assertEqual(parent_org_name, "中国化学工程第三建设有限公司")
        self.assertEqual(confidence, 0.82)
        self.assertEqual(
            sources,
            [{"title": "中国化学工程第三建设有限公司 - 官网", "url": "https://example.com/a"}],
        )


class ParentOrgNameRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app_module.app)

    def test_parent_org_name_route_returns_affiliate_org_name(self):
        with patch.object(
            app_module,
            "resolve_parent_org_with_affiliate",
            return_value={
                "affiliateOrgName": "中国化学工程第三建设有限公司",
                "parentOrgName": "中国化学工程第三建设有限公司",
                "confidence": 0.82,
                "sources": [{"title": "企查查", "url": "https://example.com/a"}],
                "route": "openai",
                "model": "gpt-5.2",
            },
        ):
            response = self.client.post(
                "/parent_org_name",
                json={"orgName": "中国化学工程第三建设有限公司采购部"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "affiliateOrgName": "中国化学工程第三建设有限公司",
                "parentOrgName": "中国化学工程第三建设有限公司",
                "confidence": 0.82,
                "sources": [{"title": "企查查", "url": "https://example.com/a"}],
            },
        )

    def test_parent_org_name_route_still_returns_400_for_invalid_request(self):
        response = self.client.post("/parent_org_name", json={"orgName": ""})

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
