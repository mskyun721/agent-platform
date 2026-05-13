"""Unit tests for Confluence MCP tools (httpx mocked — no real API calls)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server" / "src"))

from agent_platform_mcp.tools import confluence  # noqa: E402

FAKE_ENV = {
    "CONFLUENCE_URL": "https://example.atlassian.net",
    "CONFLUENCE_EMAIL": "user@example.com",
    "CONFLUENCE_API_TOKEN": "fake-token",
}


def _mock_response(status_code: int, body: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    return resp


class TestFetchPage(unittest.TestCase):
    @patch.dict(os.environ, FAKE_ENV)
    @patch("agent_platform_mcp.tools.confluence.httpx.get")
    def test_fetch_page_success(self, mock_get):
        mock_get.return_value = _mock_response(
            200,
            {
                "id": "123456",
                "title": "Auth Service Spec",
                "spaceId": "PROJ",
                "body": {
                    "storage": {
                        "value": "<p>Background: service handles JWT auth.</p><p>Rules: token expires in 1h.</p>"
                    }
                },
                "version": {"createdAt": "2026-05-01T10:00:00Z"},
            },
        )
        result = confluence.fetch_page("123456")

        self.assertEqual(result["title"], "Auth Service Spec")
        self.assertIn("Background", result["body_markdown"])
        self.assertIn("Rules", result["body_markdown"])
        self.assertEqual(result["last_modified"], "2026-05-01T10:00:00Z")
        self.assertIn("123456", result["url"])

    @patch.dict(os.environ, FAKE_ENV)
    @patch("agent_platform_mcp.tools.confluence.httpx.get")
    def test_fetch_page_not_found(self, mock_get):
        mock_get.return_value = _mock_response(404, {})
        result = confluence.fetch_page("999")
        self.assertIn("error", result)
        self.assertIn("999", result["error"])

    @patch.dict(os.environ, FAKE_ENV)
    @patch("agent_platform_mcp.tools.confluence.httpx.get")
    def test_fetch_page_auth_failure(self, mock_get):
        mock_get.return_value = _mock_response(401, {})
        result = confluence.fetch_page("123")
        self.assertIn("error", result)
        self.assertIn("auth failed", result["error"].lower())

    def test_fetch_page_missing_env_vars(self):
        clean_env = {k: v for k, v in os.environ.items() if k not in FAKE_ENV}
        with patch.dict(os.environ, clean_env, clear=True):
            result = confluence.fetch_page("123")
        self.assertIn("error", result)
        self.assertIn("CONFLUENCE_URL", result["error"])

    @patch.dict(os.environ, FAKE_ENV)
    @patch("agent_platform_mcp.tools.confluence.httpx.get")
    def test_fetch_page_timeout(self, mock_get):
        import httpx as httpx_lib
        mock_get.side_effect = httpx_lib.TimeoutException("timed out")
        result = confluence.fetch_page("123")
        self.assertIn("error", result)
        self.assertIn("timed out", result["error"].lower())


class TestListSpace(unittest.TestCase):
    @patch.dict(os.environ, FAKE_ENV)
    @patch("agent_platform_mcp.tools.confluence.httpx.get")
    def test_list_space_success(self, mock_get):
        mock_get.side_effect = [
            _mock_response(200, {"results": [{"id": "~spaceId1", "key": "PROJ"}]}),
            _mock_response(
                200,
                {
                    "results": [
                        {"id": "111", "title": "API Contract", "version": {"createdAt": "2026-04-01T00:00:00Z"}},
                        {"id": "222", "title": "Auth Design", "version": {"createdAt": "2026-04-15T00:00:00Z"}},
                    ]
                },
            ),
        ]
        result = confluence.list_space("PROJ", limit=10)

        self.assertEqual(result["space_key"], "PROJ")
        self.assertEqual(len(result["pages"]), 2)
        self.assertEqual(result["pages"][0]["id"], "111")
        self.assertEqual(result["pages"][0]["title"], "API Contract")

    @patch.dict(os.environ, FAKE_ENV)
    @patch("agent_platform_mcp.tools.confluence.httpx.get")
    def test_list_space_not_found(self, mock_get):
        mock_get.return_value = _mock_response(200, {"results": []})
        result = confluence.list_space("NOSUCHSPACE")
        self.assertIn("error", result)
        self.assertIn("NOSUCHSPACE", result["error"])

    @patch.dict(os.environ, FAKE_ENV)
    @patch("agent_platform_mcp.tools.confluence.httpx.get")
    def test_list_space_auth_failure(self, mock_get):
        mock_get.return_value = _mock_response(401, {})
        result = confluence.list_space("PROJ")
        self.assertIn("error", result)
        self.assertIn("auth failed", result["error"].lower())

    def test_list_space_missing_env_vars(self):
        clean_env = {k: v for k, v in os.environ.items() if k not in FAKE_ENV}
        with patch.dict(os.environ, clean_env, clear=True):
            result = confluence.list_space("PROJ")
        self.assertIn("error", result)
        self.assertIn("CONFLUENCE_URL", result["error"])


if __name__ == "__main__":
    unittest.main()
