"""Confluence Cloud REST API v2 tools."""

from __future__ import annotations

import base64
from html.parser import HTMLParser
from typing import Any

import httpx

from agent_platform_mcp.config import ConfigError, confluence_config

DEFAULT_TIMEOUT_SEC = 30


class _TextExtractor(HTMLParser):
    """Extract plain text from Confluence storage format HTML."""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self._chunks.append(stripped)

    def get_text(self) -> str:
        return "\n\n".join(self._chunks)


def _to_markdown(storage_html: str) -> str:
    """Convert Confluence storage-format HTML to plain text."""
    extractor = _TextExtractor()
    extractor.feed(storage_html)
    return extractor.get_text()


def _basic_auth_header(email: str, token: str) -> str:
    credentials = base64.b64encode(f"{email}:{token}".encode()).decode()
    return f"Basic {credentials}"


def fetch_page(page_id: str) -> dict[str, Any]:
    """Fetch a Confluence Cloud page by ID.

    Returns dict with keys: title, body_markdown, url, last_modified.
    Returns {"error": "..."} on failure.
    """
    try:
        cfg = confluence_config()
    except ConfigError as exc:
        return {"error": str(exc)}

    base_url = cfg["url"].rstrip("/")
    headers = {
        "Authorization": _basic_auth_header(cfg["email"], cfg["token"]),
        "Accept": "application/json",
    }

    try:
        response = httpx.get(
            f"{base_url}/wiki/api/v2/pages/{page_id}",
            params={"body-format": "storage"},
            headers=headers,
            timeout=DEFAULT_TIMEOUT_SEC,
        )
    except httpx.TimeoutException:
        return {"error": f"Confluence request timed out after {DEFAULT_TIMEOUT_SEC}s"}

    if response.status_code == 401:
        return {"error": "Confluence auth failed. Check CONFLUENCE_EMAIL / CONFLUENCE_API_TOKEN"}
    if response.status_code == 404:
        return {"error": f"Page {page_id} not found"}
    if response.status_code != 200:
        return {"error": f"Confluence API error: HTTP {response.status_code}"}

    data = response.json()
    title = data.get("title", "")
    storage_html = data.get("body", {}).get("storage", {}).get("value", "")
    body_markdown = _to_markdown(storage_html)
    last_modified = data.get("version", {}).get("createdAt", "")
    space_id = data.get("spaceId", "")
    url = f"{base_url}/wiki/spaces/{space_id}/pages/{page_id}"

    return {
        "title": title,
        "body_markdown": body_markdown,
        "url": url,
        "last_modified": last_modified,
    }


def list_space(space_key: str, limit: int = 20) -> dict[str, Any]:
    """List pages in a Confluence Cloud space by space key.

    Returns dict with keys: space_key, pages (list of {id, title, last_modified}).
    Returns {"error": "..."} on failure.
    """
    try:
        cfg = confluence_config()
    except ConfigError as exc:
        return {"error": str(exc)}

    base_url = cfg["url"].rstrip("/")
    headers = {
        "Authorization": _basic_auth_header(cfg["email"], cfg["token"]),
        "Accept": "application/json",
    }

    try:
        space_resp = httpx.get(
            f"{base_url}/wiki/api/v2/spaces",
            params={"keys": space_key, "limit": 1},
            headers=headers,
            timeout=DEFAULT_TIMEOUT_SEC,
        )
    except httpx.TimeoutException:
        return {"error": f"Confluence request timed out after {DEFAULT_TIMEOUT_SEC}s"}

    if space_resp.status_code == 401:
        return {"error": "Confluence auth failed. Check CONFLUENCE_EMAIL / CONFLUENCE_API_TOKEN"}
    if space_resp.status_code != 200:
        return {"error": f"Confluence API error: HTTP {space_resp.status_code}"}

    spaces = space_resp.json().get("results", [])
    if not spaces:
        return {"error": f"Space '{space_key}' not found"}

    space_id = spaces[0]["id"]

    try:
        pages_resp = httpx.get(
            f"{base_url}/wiki/api/v2/pages",
            params={"space-id": space_id, "limit": limit, "sort": "title"},
            headers=headers,
            timeout=DEFAULT_TIMEOUT_SEC,
        )
    except httpx.TimeoutException:
        return {"error": f"Confluence request timed out after {DEFAULT_TIMEOUT_SEC}s"}

    if pages_resp.status_code != 200:
        return {"error": f"Confluence API error: HTTP {pages_resp.status_code}"}

    pages = [
        {
            "id": p["id"],
            "title": p.get("title", ""),
            "last_modified": p.get("version", {}).get("createdAt", ""),
        }
        for p in pages_resp.json().get("results", [])
    ]

    return {"space_key": space_key, "pages": pages}
