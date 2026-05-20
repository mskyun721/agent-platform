"""Unit tests for Confluence MCP tools (httpx mocked — no real API calls)."""

from __future__ import annotations

import os
import sys
import tempfile
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


def _mock_binary_response(status_code: int, content: bytes) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    return resp


_PAGE_BODY = {
    "id": "123456",
    "title": "Auth Service Spec",
    "spaceId": "PROJ",
    "body": {"storage": {"value": "<p>Background: service handles JWT auth.</p><p>Rules: token expires in 1h.</p>"}},
    "version": {"createdAt": "2026-05-01T10:00:00Z"},
}

_SPACE_RESP = {"results": [{"id": "~spaceId1", "key": "PROJ"}]}
_PARENT_RESP = {"results": [{"id": "111", "title": "Sprint 3"}]}
_CREATE_RESP = {"id": "999", "spaceId": "~spaceId1", "title": "PRD"}


class TestFetchPage(unittest.TestCase):
    @patch.dict(os.environ, FAKE_ENV)
    @patch("agent_platform_mcp.tools.confluence.httpx.get")
    def test_fetch_page_success(self, mock_get):
        mock_get.side_effect = [
            _mock_response(200, _PAGE_BODY),
            _mock_response(200, {"results": []}),
        ]
        result = confluence.fetch_page("123456")

        self.assertEqual(result["title"], "Auth Service Spec")
        self.assertIn("Background", result["body_markdown"])
        self.assertIn("Rules", result["body_markdown"])
        self.assertEqual(result["last_modified"], "2026-05-01T10:00:00Z")
        self.assertIn("123456", result["url"])
        self.assertEqual(result["images"], [])

    @patch.dict(os.environ, FAKE_ENV)
    @patch("agent_platform_mcp.tools.confluence.httpx.get")
    def test_fetch_page_with_images(self, mock_get):
        mock_get.side_effect = [
            _mock_response(200, _PAGE_BODY),
            _mock_response(200, {"results": [
                {"id": "att001", "title": "schema.drawio.png", "mediaType": "image/png"},
                {"id": "att002", "title": "flow.drawio", "mediaType": "application/vnd.jgraph.mxfile"},
            ]}),
            _mock_binary_response(200, b"\x89PNG fake-image-bytes"),
        ]
        result = confluence.fetch_page("123456")

        self.assertIn("images", result)
        self.assertEqual(len(result["images"]), 1)
        self.assertEqual(result["images"][0]["filename"], "schema.drawio.png")
        self.assertTrue(result["images"][0]["local_path"].endswith("schema.drawio.png"))
        self.assertTrue(Path(result["images"][0]["local_path"]).exists())

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


# ---------------------------------------------------------------------------
# Markdown conversion tests
# ---------------------------------------------------------------------------

class TestMarkdownToStorage(unittest.TestCase):
    def _convert(self, md: str) -> str:
        return confluence._markdown_to_storage(md)

    def test_headings(self):
        for level in range(1, 7):
            hashes = "#" * level
            result = self._convert(f"{hashes} Title\n")
            self.assertIn(f"<h{level}>Title</h{level}>", result)

    def test_bold(self):
        result = self._convert("**bold text**\n")
        self.assertIn("<strong>bold text</strong>", result)

    def test_italic(self):
        result = self._convert("*italic text*\n")
        self.assertIn("<em>italic text</em>", result)

    def test_bold_not_broken_by_italic_regex(self):
        result = self._convert("**two words**\n")
        self.assertIn("<strong>two words</strong>", result)
        self.assertNotIn("<em>", result)

    def test_inline_code(self):
        result = self._convert("`some code`\n")
        self.assertIn("<code>some code</code>", result)

    def test_fenced_code_with_language(self):
        md = "```kotlin\nfun foo() {}\n```\n"
        result = self._convert(md)
        self.assertIn('ac:name="code"', result)
        self.assertIn('ac:name="language">kotlin</ac:parameter>', result)
        self.assertIn("<![CDATA[fun foo() {}]]>", result)

    def test_fenced_code_no_language(self):
        md = "```\nsome code\n```\n"
        result = self._convert(md)
        self.assertIn('ac:name="code"', result)
        self.assertIn("<![CDATA[some code]]>", result)

    def test_ul_grouping(self):
        md = "- item one\n- item two\n- item three\n"
        result = self._convert(md)
        self.assertEqual(result.count("<ul>"), 1, "Should produce exactly one <ul> tag")
        self.assertEqual(result.count("</ul>"), 1)
        self.assertEqual(result.count("<li>"), 3)

    def test_ol_grouping(self):
        md = "1. first\n2. second\n3. third\n"
        result = self._convert(md)
        self.assertEqual(result.count("<ol>"), 1)
        self.assertEqual(result.count("</ol>"), 1)
        self.assertEqual(result.count("<li>"), 3)

    def test_horizontal_rule(self):
        result = self._convert("before\n\n---\n\nafter\n")
        self.assertIn("<hr />", result)

    def test_link(self):
        result = self._convert("[click here](https://example.com)\n")
        self.assertIn('<a href="https://example.com">click here</a>', result)

    def test_html_escape_in_text(self):
        result = self._convert("Use <b> & > signs carefully\n")
        self.assertIn("&lt;b&gt;", result)
        self.assertIn("&amp;", result)

    def test_frontmatter_stripped(self):
        md = "---\ntitle: My PRD\nstatus: draft\n---\n\n# Real Heading\n"
        result = self._convert(md)
        # frontmatter delimiters must not produce <hr /> or raw YAML text
        self.assertNotIn("title: My PRD", result)
        self.assertNotIn("status: draft", result)
        self.assertIn("<h1>Real Heading</h1>", result)
        # Only one <hr /> should NOT be present from frontmatter
        self.assertNotIn("<hr />", result)

    def test_paragraph_wrapping(self):
        result = self._convert("Hello world\n")
        self.assertIn("<p>Hello world</p>", result)


# ---------------------------------------------------------------------------
# create_page tests
# ---------------------------------------------------------------------------

class TestCreatePage(unittest.TestCase):
    @patch.dict(os.environ, FAKE_ENV)
    @patch("agent_platform_mcp.tools.confluence.httpx.post")
    @patch("agent_platform_mcp.tools.confluence.httpx.get")
    def test_create_page_success(self, mock_get, mock_post):
        mock_get.side_effect = [
            _mock_response(200, _SPACE_RESP),
            _mock_response(200, _PARENT_RESP),
        ]
        mock_post.return_value = _mock_response(201, _CREATE_RESP)

        result = confluence.create_page("PROJ", "Sprint 3", "PRD", "# PRD\nContent")

        self.assertIn("title", result)
        self.assertIn("page_id", result)
        self.assertIn("url", result)
        self.assertEqual(result["page_id"], "999")
        self.assertIn("999", result["url"])

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs["json"]
        self.assertEqual(payload["spaceId"], "~spaceId1")
        self.assertEqual(payload["parentId"], "111")
        self.assertEqual(payload["title"], "PRD")
        self.assertEqual(payload["body"]["representation"], "storage")

    @patch.dict(os.environ, FAKE_ENV)
    @patch("agent_platform_mcp.tools.confluence.httpx.get")
    def test_create_page_space_not_found(self, mock_get):
        mock_get.return_value = _mock_response(200, {"results": []})
        result = confluence.create_page("BADSPACE", "Parent", "Title", "body")
        self.assertIn("error", result)
        self.assertIn("BADSPACE", result["error"])

    @patch.dict(os.environ, FAKE_ENV)
    @patch("agent_platform_mcp.tools.confluence.httpx.get")
    def test_create_page_parent_not_found(self, mock_get):
        mock_get.side_effect = [
            _mock_response(200, _SPACE_RESP),
            _mock_response(200, {"results": []}),
        ]
        result = confluence.create_page("PROJ", "NonExistentParent", "Title", "body")
        self.assertIn("error", result)
        self.assertIn("NonExistentParent", result["error"])

    @patch.dict(os.environ, FAKE_ENV)
    @patch("agent_platform_mcp.tools.confluence.httpx.post")
    @patch("agent_platform_mcp.tools.confluence.httpx.get")
    def test_create_page_duplicate_400(self, mock_get, mock_post):
        mock_get.side_effect = [
            _mock_response(200, _SPACE_RESP),
            _mock_response(200, _PARENT_RESP),
        ]
        mock_post.return_value = _mock_response(400, {
            "errors": [{"title": "A page with this title already exists"}]
        })
        result = confluence.create_page("PROJ", "Sprint 3", "PRD", "body")
        self.assertIn("error", result)
        self.assertIn("already exists", result["error"])

    @patch.dict(os.environ, FAKE_ENV)
    @patch("agent_platform_mcp.tools.confluence.httpx.get")
    def test_create_page_auth_failure(self, mock_get):
        mock_get.return_value = _mock_response(401, {})
        result = confluence.create_page("PROJ", "Parent", "Title", "body")
        self.assertIn("error", result)
        self.assertIn("auth failed", result["error"].lower())

    def test_create_page_missing_env(self):
        clean_env = {k: v for k, v in os.environ.items() if k not in FAKE_ENV}
        with patch.dict(os.environ, clean_env, clear=True):
            result = confluence.create_page("PROJ", "Parent", "Title", "body")
        self.assertIn("error", result)
        self.assertIn("CONFLUENCE_URL", result["error"])

    @patch.dict(os.environ, FAKE_ENV)
    @patch("agent_platform_mcp.tools.confluence.httpx.post")
    @patch("agent_platform_mcp.tools.confluence.httpx.get")
    def test_create_page_post_timeout(self, mock_get, mock_post):
        import httpx as httpx_lib
        mock_get.side_effect = [
            _mock_response(200, _SPACE_RESP),
            _mock_response(200, _PARENT_RESP),
        ]
        mock_post.side_effect = httpx_lib.TimeoutException("timed out")
        result = confluence.create_page("PROJ", "Sprint 3", "PRD", "body")
        self.assertIn("error", result)
        self.assertIn("timed out", result["error"].lower())


# ---------------------------------------------------------------------------
# sync_feature tests
# ---------------------------------------------------------------------------

class TestSyncFeature(unittest.TestCase):
    def _make_feature_dir(self, tmp_path: Path, feature: str, files: dict[str, str]) -> Path:
        feature_dir = tmp_path / "docs" / "features" / feature
        feature_dir.mkdir(parents=True)
        for name, content in files.items():
            (feature_dir / name).write_text(content, encoding="utf-8")
        return feature_dir

    @patch.dict(os.environ, FAKE_ENV)
    @patch("agent_platform_mcp.tools.confluence.httpx.post")
    @patch("agent_platform_mcp.tools.confluence.httpx.get")
    @patch("agent_platform_mcp.tools.confluence.target_project_root")
    def test_sync_success(self, mock_root, mock_get, mock_post):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._make_feature_dir(tmp_path, "my-feature", {
                "PRD.md": "# PRD\nContent A",
                "TASK.md": "# TASK\nContent B",
            })
            mock_root.return_value = tmp_path

            mock_get.side_effect = [
                _mock_response(200, _SPACE_RESP),
                _mock_response(200, _PARENT_RESP),
                _mock_response(200, _SPACE_RESP),
                _mock_response(200, _PARENT_RESP),
            ]
            mock_post.side_effect = [
                _mock_response(201, {"id": "801", "spaceId": "~spaceId1", "title": "PRD"}),
                _mock_response(201, {"id": "802", "spaceId": "~spaceId1", "title": "TASK"}),
            ]

            result = confluence.sync_feature("PROJ", "Sprint 3", "my-feature")

        self.assertEqual(result["feature"], "my-feature")
        self.assertEqual(len(result["results"]), 2)
        statuses = {r["file"]: r["status"] for r in result["results"]}
        self.assertEqual(statuses["PRD.md"], "created")
        self.assertEqual(statuses["TASK.md"], "created")

    @patch("agent_platform_mcp.tools.confluence.target_project_root")
    def test_sync_no_active_project(self, mock_root):
        mock_root.return_value = None
        result = confluence.sync_feature("PROJ", "Sprint 3", "my-feature")
        self.assertIn("error", result)
        self.assertIn("active project", result["error"].lower())

    @patch("agent_platform_mcp.tools.confluence.target_project_root")
    def test_sync_feature_dir_not_found(self, mock_root):
        with tempfile.TemporaryDirectory() as tmp:
            mock_root.return_value = Path(tmp)
            result = confluence.sync_feature("PROJ", "Sprint 3", "nonexistent-feature")
        self.assertIn("error", result)
        self.assertIn("not found", result["error"].lower())

    @patch.dict(os.environ, FAKE_ENV)
    @patch("agent_platform_mcp.tools.confluence.httpx.post")
    @patch("agent_platform_mcp.tools.confluence.httpx.get")
    @patch("agent_platform_mcp.tools.confluence.target_project_root")
    def test_sync_partial_failure(self, mock_root, mock_get, mock_post):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._make_feature_dir(tmp_path, "feat", {
                "PRD.md": "# PRD",
                "REVIEW.md": "# REVIEW",
            })
            mock_root.return_value = tmp_path

            mock_get.side_effect = [
                _mock_response(200, _SPACE_RESP),
                _mock_response(200, _PARENT_RESP),
                _mock_response(200, _SPACE_RESP),
                _mock_response(200, _PARENT_RESP),
            ]
            mock_post.side_effect = [
                _mock_response(201, {"id": "901", "spaceId": "~spaceId1", "title": "PRD"}),
                _mock_response(400, {"errors": [{"title": "Page already exists"}]}),
            ]

            result = confluence.sync_feature("PROJ", "Sprint 3", "feat")

        self.assertEqual(len(result["results"]), 2)
        statuses = {r["file"]: r["status"] for r in result["results"]}
        self.assertEqual(statuses["PRD.md"], "created")
        self.assertEqual(statuses["REVIEW.md"], "error")

    @patch.dict(os.environ, FAKE_ENV)
    @patch("agent_platform_mcp.tools.confluence.httpx.post")
    @patch("agent_platform_mcp.tools.confluence.httpx.get")
    @patch("agent_platform_mcp.tools.confluence.target_project_root")
    def test_sync_skips_non_md_files(self, mock_root, mock_get, mock_post):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            feature_dir = tmp_path / "docs" / "features" / "feat"
            feature_dir.mkdir(parents=True)
            (feature_dir / "PRD.md").write_text("# PRD", encoding="utf-8")
            (feature_dir / "diagram.png").write_bytes(b"\x89PNG")
            (feature_dir / "notes.txt").write_text("notes", encoding="utf-8")
            mock_root.return_value = tmp_path

            mock_get.side_effect = [
                _mock_response(200, _SPACE_RESP),
                _mock_response(200, _PARENT_RESP),
            ]
            mock_post.return_value = _mock_response(201, {"id": "901", "spaceId": "~spaceId1", "title": "PRD"})

            result = confluence.sync_feature("PROJ", "Sprint 3", "feat")

        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["file"], "PRD.md")
        self.assertEqual(mock_post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
