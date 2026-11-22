"""Confluence Cloud REST API v2 tools."""

from __future__ import annotations

import base64
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from agent_platform_mcp import markdown_blocks, secret_scan
from agent_platform_mcp.config import ConfigError, confluence_config, resolve_project_dir, target_project_root
# Re-exported: the overview builder moved to a target-neutral module shared with Notion.
from agent_platform_mcp.tools.feature_overview import _blocks_to_markdown, build_overview_markdown  # noqa: F401
from agent_platform_mcp.tools.feature_overview import attachment_blocked_reason, feature_location, publishable_files
from agent_platform_mcp.tools.spec_publish_map import (
    OWNER_LABEL,
    OWNER_PROPERTY,
    AcceptOwner,
    owner_marker,
    owner_matches,
    valid_confluence_page_id,
)

DEFAULT_TIMEOUT_SEC = 30


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

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


def _client_context(func_name: str) -> tuple[str, dict] | dict:
    """Return (base_url, headers) or an error dict if config is missing."""
    try:
        cfg = confluence_config()
    except ConfigError as exc:
        return {"error": str(exc)}
    base_url = cfg["url"].rstrip("/")
    headers = {
        "Authorization": _basic_auth_header(cfg["email"], cfg["token"]),
        "Accept": "application/json",
    }
    return base_url, headers


AUTH_FAILED = "Confluence auth failed. Check CONFLUENCE_EMAIL / CONFLUENCE_API_TOKEN"
TIMED_OUT = f"Confluence request timed out after {DEFAULT_TIMEOUT_SEC}s"


def _http_error(resp: Any, message: str | None = None) -> dict[str, Any]:
    """Structured status error `{"error", "http_status"}`; never carries the response body."""
    status = resp.status_code
    text = AUTH_FAILED if status == 401 else message or f"Confluence API error: HTTP {status}"
    return {"error": text, "http_status": status}


def _download_images(page_id: str, base_url: str, headers: dict) -> list[dict[str, str]]:
    """Download PNG attachments from a Confluence page.

    Saves to /tmp/confluence_images/{page_id}/ and returns
    [{filename, local_path}]. Returns [] on any failure — never raises.
    """
    try:
        resp = httpx.get(
            f"{base_url}/wiki/api/v2/pages/{page_id}/attachments",
            headers=headers,
            timeout=DEFAULT_TIMEOUT_SEC,
        )
    except httpx.RequestError:
        return []

    if resp.status_code != 200:
        return []

    try:
        attachments = resp.json().get("results", [])
    except ValueError:
        return []

    save_dir = Path(f"/tmp/confluence_images/{page_id}")
    save_dir.mkdir(parents=True, exist_ok=True)

    download_headers = {k: v for k, v in headers.items() if k != "Accept"}
    images = []
    for att in attachments:
        if att.get("mediaType") != "image/png":
            continue
        att_id = att.get("id", "")
        filename = att.get("title", "image.png")
        if not att_id:
            continue

        try:
            img_resp = httpx.get(
                f"{base_url}/wiki/rest/api/content/{page_id}/child/attachment/{att_id}/download",
                headers=download_headers,
                follow_redirects=True,
                timeout=DEFAULT_TIMEOUT_SEC,
            )
        except httpx.RequestError:
            continue

        if img_resp.status_code != 200:
            continue

        local_path = save_dir / filename
        local_path.write_bytes(img_resp.content)
        images.append({"filename": filename, "local_path": str(local_path)})

    return images


# ---------------------------------------------------------------------------
# Shared API helpers
# ---------------------------------------------------------------------------

def _resolve_space_id(space_key: str, base_url: str, headers: dict) -> str | dict:
    """Look up a Confluence space ID by space key.

    Returns the space ID string on success, or {"error": "..."} on failure.
    """
    try:
        resp = httpx.get(
            f"{base_url}/wiki/api/v2/spaces",
            params={"keys": space_key, "limit": 1},
            headers=headers,
            timeout=DEFAULT_TIMEOUT_SEC,
        )
    except httpx.RequestError:
        return {"error": f"Confluence request timed out after {DEFAULT_TIMEOUT_SEC}s"}

    if resp.status_code != 200:
        return _http_error(resp)

    try:
        results = resp.json().get("results", [])
    except ValueError:
        return {"error": "Confluence returned a non-JSON response"}

    if not results:
        return {"error": f"Space '{space_key}' not found"}

    space_id = results[0].get("id")
    if not space_id:
        return {"error": f"Space '{space_key}' returned no ID"}

    return space_id


def _resolve_page_id(title: str, space_id: str, base_url: str, headers: dict) -> str | dict:
    """Look up a Confluence page ID by title within a space.

    Returns the page ID string on success, or {"error": "..."} on failure.
    The title match is exact and case-sensitive.
    """
    try:
        resp = httpx.get(
            f"{base_url}/wiki/api/v2/pages",
            params={"space-id": space_id, "title": title, "limit": 1},
            headers=headers,
            timeout=DEFAULT_TIMEOUT_SEC,
        )
    except httpx.RequestError:
        return {"error": f"Confluence request timed out after {DEFAULT_TIMEOUT_SEC}s"}

    if resp.status_code != 200:
        return _http_error(resp)

    try:
        results = resp.json().get("results", [])
    except ValueError:
        return {"error": "Confluence returned a non-JSON response"}

    if not results:
        return {"error": f"Page '{title}' not found in space (ID: {space_id})"}

    page_id = results[0].get("id")
    if not page_id:
        return {"error": f"Page '{title}' returned no ID"}

    return page_id


# ---------------------------------------------------------------------------
# Markdown → Confluence storage format conversion
# ---------------------------------------------------------------------------

def _markdown_to_storage(md: str) -> str:
    """Convert Markdown text to Confluence storage format (XML/HTML subset).

    Parsing lives in `agent_platform_mcp.markdown_blocks` so the local review view and
    Confluence render the same block shapes (tables, task lists, quotes, code, lists).
    """
    return markdown_blocks.render_storage(markdown_blocks.parse(md))


# ---------------------------------------------------------------------------
# Public read functions
# ---------------------------------------------------------------------------

def fetch_page(page_id: str) -> dict[str, Any]:
    """Fetch a Confluence Cloud page by ID.

    Returns dict with keys: title, body_markdown, url, last_modified.
    Returns {"error": "..."} on failure.
    """
    ctx = _client_context("fetch_page")
    if isinstance(ctx, dict):
        return ctx
    base_url, headers = ctx

    try:
        response = httpx.get(
            f"{base_url}/wiki/api/v2/pages/{page_id}",
            params={"body-format": "storage"},
            headers=headers,
            timeout=DEFAULT_TIMEOUT_SEC,
        )
    except httpx.RequestError:
        return {"error": f"Confluence request timed out after {DEFAULT_TIMEOUT_SEC}s"}

    if response.status_code == 401:
        return {"error": "Confluence auth failed. Check CONFLUENCE_EMAIL / CONFLUENCE_API_TOKEN"}
    if response.status_code == 404:
        return {"error": f"Page {page_id} not found"}
    if response.status_code != 200:
        return {"error": f"Confluence API error: HTTP {response.status_code}"}

    try:
        data = response.json()
    except ValueError:
        return {"error": "Confluence returned a non-JSON response"}

    title = data.get("title", "")
    storage_html = data.get("body", {}).get("storage", {}).get("value", "")
    body_markdown = _to_markdown(storage_html)
    last_modified = data.get("version", {}).get("createdAt", "")
    space_id = data.get("spaceId", "")
    url = f"{base_url}/wiki/spaces/{space_id}/pages/{page_id}"

    images = _download_images(page_id, base_url, headers)
    return {
        "title": title,
        "body_markdown": body_markdown,
        "url": url,
        "last_modified": last_modified,
        "images": images,
    }


def list_space(space_key: str, limit: int = 20) -> dict[str, Any]:
    """List pages in a Confluence Cloud space by space key.

    Returns dict with keys: space_key, pages (list of {id, title, last_modified}).
    Returns {"error": "..."} on failure.
    """
    ctx = _client_context("list_space")
    if isinstance(ctx, dict):
        return ctx
    base_url, headers = ctx

    space_id = _resolve_space_id(space_key, base_url, headers)
    if isinstance(space_id, dict):
        return space_id

    try:
        pages_resp = httpx.get(
            f"{base_url}/wiki/api/v2/pages",
            params={"space-id": space_id, "limit": limit, "sort": "title"},
            headers=headers,
            timeout=DEFAULT_TIMEOUT_SEC,
        )
    except httpx.RequestError:
        return {"error": f"Confluence request timed out after {DEFAULT_TIMEOUT_SEC}s"}

    if pages_resp.status_code == 401:
        return {"error": "Confluence auth failed. Check CONFLUENCE_EMAIL / CONFLUENCE_API_TOKEN"}
    if pages_resp.status_code != 200:
        return {"error": f"Confluence API error: HTTP {pages_resp.status_code}"}

    try:
        pages_data = pages_resp.json()
    except ValueError:
        return {"error": "Confluence returned a non-JSON response"}

    pages = [
        {
            "id": p["id"],
            "title": p.get("title", ""),
            "last_modified": p.get("version", {}).get("createdAt", ""),
        }
        for p in pages_data.get("results", [])
    ]

    return {"space_key": space_key, "pages": pages}


# ---------------------------------------------------------------------------
# Public write functions
# ---------------------------------------------------------------------------

def create_page(
    space_key: str,
    parent_title: str,
    title: str,
    body_markdown: str,
) -> dict[str, Any]:
    """Create a new Confluence Cloud page under the specified parent page.

    Converts body_markdown (Markdown text) to Confluence storage format.
    Returns {"title", "page_id", "url"} on success, or {"error": "..."} on failure.
    Duplicate page titles result in an error (no overwrite).
    """
    ctx = _client_context("create_page")
    if isinstance(ctx, dict):
        return ctx
    base_url, headers = ctx

    space_id = _resolve_space_id(space_key, base_url, headers)
    if isinstance(space_id, dict):
        return space_id

    parent_id = _resolve_page_id(parent_title, space_id, base_url, headers)
    if isinstance(parent_id, dict):
        return parent_id

    return _create_page_by_id(base_url, headers, space_id, parent_id, title, _markdown_to_storage(body_markdown))


def _create_page_by_id(
    base_url: str, headers: dict, space_id: str, parent_id: str, title: str, storage_body: str,
) -> dict[str, Any]:
    """POST one page whose body is already storage format; ids resolved by the caller."""
    post_headers = {**headers, "Content-Type": "application/json"}
    payload = {
        "spaceId": space_id,
        "parentId": parent_id,
        "title": title,
        "status": "current",
        "body": {"representation": "storage", "value": storage_body},
    }

    try:
        resp = httpx.post(
            f"{base_url}/wiki/api/v2/pages",
            json=payload,
            headers=post_headers,
            timeout=DEFAULT_TIMEOUT_SEC,
        )
    except httpx.RequestError:
        return {"error": f"Confluence request timed out after {DEFAULT_TIMEOUT_SEC}s"}

    if resp.status_code == 401:
        return _http_error(resp)

    if resp.status_code == 400:
        try:
            detail = resp.json()
            errors = detail.get("errors", [])
            msg = errors[0].get("title", "Bad request") if errors else "Bad request"
        except (ValueError, IndexError, KeyError):
            msg = "Bad request"
        return {"error": f"Confluence rejected page creation: {msg}", "http_status": 400}

    if resp.status_code not in (200, 201):
        return _http_error(resp)

    try:
        data = resp.json()
    except ValueError:
        return {"error": "Confluence returned a non-JSON response"}

    page_id = data.get("id", "")
    url = f"{base_url}/wiki/spaces/{space_id}/pages/{page_id}"
    return {"title": title, "page_id": page_id, "url": url}


def _upload_attachment(base_url: str, headers: dict, page_id: str, path: Path) -> dict[str, Any]:
    """Attach one file to a page (REST v1; v2 has no attachment upload). Same-name uploads
    become a new attachment version on the Confluence side."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        return {"file": path.name, "status": "error", "error": str(exc)}
    try:
        resp = httpx.post(
            f"{base_url}/wiki/rest/api/content/{page_id}/child/attachment",
            headers={**headers, "X-Atlassian-Token": "nocheck"},
            files={"file": (path.name, data, "application/octet-stream")},
            timeout=DEFAULT_TIMEOUT_SEC,
        )
    except httpx.RequestError:
        return {"file": path.name, "status": "error", "error": f"Confluence request timed out after {DEFAULT_TIMEOUT_SEC}s"}
    if resp.status_code == 400:
        # Same-name attachment already exists: upload as a new version of it.
        try:
            found = httpx.get(
                f"{base_url}/wiki/rest/api/content/{page_id}/child/attachment",
                headers=headers,
                params={"filename": path.name},
                timeout=DEFAULT_TIMEOUT_SEC,
            )
            results = found.json().get("results", []) if found.status_code == 200 else []
            if results:
                resp = httpx.post(
                    f"{base_url}/wiki/rest/api/content/{page_id}/child/attachment/{results[0]['id']}/data",
                    headers={**headers, "X-Atlassian-Token": "nocheck"},
                    files={"file": (path.name, data, "application/octet-stream")},
                    timeout=DEFAULT_TIMEOUT_SEC,
                )
        except (httpx.RequestError, ValueError, KeyError):
            return {"file": path.name, "status": "error", "error": "Confluence attachment update failed"}
    if resp.status_code not in (200, 201):
        return {"file": path.name, "status": "error", "error": f"Confluence API error: HTTP {resp.status_code}"}
    return {"file": path.name, "status": "uploaded", "page_id": page_id}


def attach_file(page_id: str, file_path: str) -> dict[str, Any]:
    """Attach a local file (e.g. .drawio, .png) to an existing page by ID.

    Same-name uploads become a new attachment version. Returns
    {"file", "status", "page_id"} on success, or {"error": "..."} on failure.
    """
    ctx = _client_context("attach_file")
    if isinstance(ctx, dict):
        return ctx
    base_url, headers = ctx

    path = Path(file_path).expanduser()
    if not path.is_file():
        return {"error": f"File not found: {file_path}"}
    result = _upload_attachment(base_url, headers, page_id, path)
    if result.get("status") != "uploaded":
        return {"error": result.get("error", "upload failed")}
    return result


def _send(method: str, url: str, headers: dict, **kwargs: Any) -> Any:
    """One request; a transport failure comes back as {"error"} (never raises)."""
    try:
        return getattr(httpx, method)(url, headers=headers, timeout=DEFAULT_TIMEOUT_SEC, **kwargs)
    except httpx.RequestError:
        return {"error": TIMED_OUT}


def _json(resp: Any) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        data = None
    return data if isinstance(data, dict) else {"error": "Confluence returned a non-JSON response"}


# v2 page status values that must never be written back to `current` (that would restore them).
_GONE_STATUSES = frozenset({"trashed", "deleted", "historical"})


def _get_page(base_url: str, headers: dict, page_id: str) -> dict[str, Any]:
    resp = _send("get", f"{base_url}/wiki/api/v2/pages/{page_id}", headers)
    if isinstance(resp, dict):
        return resp
    if resp.status_code == 404:
        return _http_error(resp, f"Page {page_id} not found")
    if resp.status_code != 200:
        return _http_error(resp)
    return _json(resp)


def _gone_error(page_id: str, status: str) -> dict[str, Any]:
    return {"error": f"Page {page_id} is {status}; it is not restored", "page_status": status}


def _put_page(base_url: str, headers: dict, page_id: str, current: dict[str, Any],
              title: str, storage_body: str) -> dict[str, Any]:
    """PUT the page as version+1. A 409 (someone saved in between) re-reads the page once and
    retries once; 401/404/409 and other statuses come back as {"error", "http_status"}."""
    for attempt in (1, 2):
        try:
            version = int((current.get("version") or {}).get("number", 0)) + 1
        except (TypeError, ValueError):
            return {"error": "Confluence returned an invalid page version"}
        payload = {
            "id": page_id,
            "status": "current",
            "title": title,
            "body": {"representation": "storage", "value": storage_body},
            "version": {"number": version},
        }
        resp = _send("put", f"{base_url}/wiki/api/v2/pages/{page_id}",
                     {**headers, "Content-Type": "application/json"}, json=payload)
        if isinstance(resp, dict):
            return resp
        if resp.status_code in (200, 201):
            space_id = current.get("spaceId", "")
            return {"title": title, "page_id": page_id,
                    "url": f"{base_url}/wiki/spaces/{space_id}/pages/{page_id}", "version": version}
        if resp.status_code != 409 or attempt == 2:
            messages = {404: f"Page {page_id} not found", 409: "Confluence version conflict after one retry"}
            return _http_error(resp, messages.get(resp.status_code))
        current = _get_page(base_url, headers, page_id)
        if "error" in current:
            return current
        if current.get("status") in _GONE_STATUSES:
            return _gone_error(page_id, current["status"])
    raise AssertionError("unreachable")


def update_page(page_id: str, body_markdown: str, title: str = "") -> dict[str, Any]:
    """Replace the body of an existing page (or draft) by ID with converted Markdown.

    An empty title keeps the current one; an untitled draft needs a title. A trashed page is
    refused (an update would restore it). Returns {"title", "page_id", "url", "version"} on
    success, or {"error": "..."}; HTTP failures also carry `http_status` (409 is retried once).
    """
    if valid_confluence_page_id(page_id) is None:
        return {"error": "invalid page id"}
    ctx = _client_context("update_page")
    if isinstance(ctx, dict):
        return ctx
    base_url, headers = ctx

    data = _get_page(base_url, headers, page_id)
    if "error" in data:
        return data
    if data.get("status") in _GONE_STATUSES:
        return _gone_error(page_id, data["status"])
    new_title = title or data.get("title", "")
    if not new_title:
        return {"error": "Page has no title; pass title"}
    return _put_page(base_url, headers, page_id, data, new_title, _markdown_to_storage(body_markdown))


# ---------------------------------------------------------------------------
# Owned SPEC/INDEX pages (BR-7): marker, direct children, upsert
# ---------------------------------------------------------------------------

MAX_CHILD_REQUESTS = 200  # 250 per request → 50k direct children before giving up


def _next_cursor(data: dict[str, Any]) -> str | None:
    """Cursor from `_links.next`; only the cursor is reused, never the link's host or path."""
    link = (data.get("_links") or {}).get("next")
    if not isinstance(link, str):
        return None
    values = parse_qs(urlsplit(link).query).get("cursor")
    return values[0] if values else None


def _list_children(base_url: str, headers: dict, parent_id: str) -> list[dict[str, Any]] | dict[str, Any]:
    """Every direct child page of `parent_id` (v2 cursor pagination to the end)."""
    found: list[dict[str, Any]] = []
    cursor: str | None = None
    seen: set[str] = set()
    for _ in range(MAX_CHILD_REQUESTS):
        params: dict[str, Any] = {"limit": 250}
        if cursor:
            params["cursor"] = cursor
        resp = _send("get", f"{base_url}/wiki/api/v2/pages/{parent_id}/children", headers, params=params)
        if isinstance(resp, dict):
            return resp
        if resp.status_code != 200:
            return _http_error(resp, f"Page {parent_id} not found" if resp.status_code == 404 else None)
        data = _json(resp)
        if "error" in data:
            return data
        found += [r for r in data.get("results") or []
                  if isinstance(r, dict) and valid_confluence_page_id(r.get("id"))]
        cursor = _next_cursor(data)
        if not cursor:
            return found
        if cursor in seen:
            return {"error": "Confluence child listing did not advance"}
        seen.add(cursor)
    return {"error": f"Confluence parent has more than {MAX_CHILD_REQUESTS * 250} child pages"}


def _owner_property(base_url: str, headers: dict, page_id: str) -> dict[str, Any]:
    """{"property": <content property or None>} for `agent-platform`, or an error."""
    resp = _send("get", f"{base_url}/wiki/api/v2/pages/{page_id}/properties", headers,
                 params={"key": OWNER_PROPERTY})
    if isinstance(resp, dict):
        return resp
    if resp.status_code != 200:
        return _http_error(resp)
    data = _json(resp)
    if "error" in data:
        return data
    matches = [p for p in data.get("results") or [] if isinstance(p, dict) and p.get("key") == OWNER_PROPERTY]
    return {"property": matches[0] if matches else None}


def _write_owner(base_url: str, headers: dict, page_id: str, owner: dict[str, str],
                 prop: dict[str, Any] | None) -> dict[str, Any] | None:
    """Create or replace the ownership property; None on success, else the error."""
    post_headers = {**headers, "Content-Type": "application/json"}
    if prop is None:
        resp = _send("post", f"{base_url}/wiki/api/v2/pages/{page_id}/properties", post_headers,
                     json={"key": OWNER_PROPERTY, "value": owner})
    else:
        prop_id = valid_confluence_page_id(prop.get("id"))  # same decimal id shape as pages
        if prop_id is None:
            return {"error": "Confluence returned an invalid property id"}
        try:
            version = int((prop.get("version") or {}).get("number", 0)) + 1
        except (TypeError, ValueError):
            return {"error": "Confluence returned an invalid property version"}
        resp = _send("put", f"{base_url}/wiki/api/v2/pages/{page_id}/properties/{prop_id}", post_headers,
                     json={"key": OWNER_PROPERTY, "value": owner, "version": {"number": version}})
    if isinstance(resp, dict):
        return resp
    return None if resp.status_code in (200, 201) else _http_error(resp)


def _add_label(base_url: str, headers: dict, page_id: str) -> str | None:
    """Add the discovery label (REST v1; v2 cannot write labels). Re-adding is a no-op."""
    resp = _send("post", f"{base_url}/wiki/rest/api/content/{page_id}/label",
                 {**headers, "Content-Type": "application/json"},
                 json=[{"prefix": "global", "name": OWNER_LABEL}])
    if isinstance(resp, dict):
        return f"label not added: {resp['error']}"
    return None if resp.status_code in (200, 201) else f"label not added: HTTP {resp.status_code}"


def _owned_state(base_url: str, headers: dict, page_id: str, owner: dict[str, str],
                 accept_owner: AcceptOwner | None) -> dict[str, Any]:
    found = _owner_property(base_url, headers, page_id)
    if "error" in found:
        return found
    prop = found["property"]
    value = prop.get("value") if prop else None
    return {"owned": owner_matches(value, owner, accept_owner), "property": prop, "exact": value == owner}


def upsert_owned_page(
    space_key: str,
    parent_title: str,
    title: str,
    body_markdown: str,
    owner: dict[str, str],
    known_page_id: str | None = None,
    accept_owner: AcceptOwner | None = None,
) -> dict[str, Any]:
    """Create or update the page `owner` owns directly under `parent_title` (BR-7).

    1. `known_page_id` (the mapping) is used when it is current, its parent is the configured
       parent and its `agent-platform` property matches `owner`. A trashed or missing page,
       another parent or a missing marker → the mapping is ignored (the page is not touched).
    2. Otherwise only the parent's direct children are searched by exact title: the owned one
       is updated; a same-title page without the marker → {"error": "title_conflict"}.
       A same-title page elsewhere in the space is never searched for or touched.
    3. Otherwise a page is created and marked (property + label `agent-platform-spec`).

    Updates are version+1 with one re-read and retry on 409. Returns {"action": "created"|
    "updated", "page_id", "title", "url", "version"?, "warning"?} or {"error", "http_status"?}.
    `accept_owner` may adopt a same-slug marker of another project_id; it is then rewritten.
    """
    try:
        owner = owner_marker((owner or {}).get("project_id"), (owner or {}).get("slug"))
    except (ValueError, AttributeError) as exc:
        return {"error": str(exc) if isinstance(exc, ValueError) else "invalid owner"}
    if known_page_id is not None and valid_confluence_page_id(known_page_id) is None:
        return {"error": "invalid page id"}
    if not isinstance(title, str) or not title.strip():
        return {"error": "title is required"}

    ctx = _client_context("upsert_owned_page")
    if isinstance(ctx, dict):
        return ctx
    base_url, headers = ctx
    space_id = _resolve_space_id(space_key, base_url, headers)
    if isinstance(space_id, dict):
        return space_id
    # The parent itself is still located by title; BR-7 bans that search for SPEC pages only.
    parent_id = _resolve_page_id(parent_title, space_id, base_url, headers)
    if isinstance(parent_id, dict):
        return parent_id
    storage = _markdown_to_storage(body_markdown)

    target: dict[str, Any] | None = None  # {"page": data, "state": owned state}
    if known_page_id is not None:
        page = _get_page(base_url, headers, known_page_id)
        if "error" in page and page.get("http_status") != 404:
            return page
        if ("error" not in page and page.get("status") == "current"
                and str(page.get("parentId", "")) == str(parent_id)):
            state = _owned_state(base_url, headers, known_page_id, owner, accept_owner)
            if "error" in state:
                return state
            if state["owned"]:
                target = {"page_id": known_page_id, "page": page, "state": state}

    if target is None:
        children = _list_children(base_url, headers, parent_id)
        if isinstance(children, dict):
            return children
        same = [c for c in children if c.get("title") == title and c.get("status", "current") == "current"]
        for child in same:
            state = _owned_state(base_url, headers, child["id"], owner, accept_owner)
            if "error" in state:
                return state
            if state["owned"]:
                target = {"page_id": child["id"], "page": None, "state": state}
                break
        else:
            if same:
                return {"error": "title_conflict", "title": title, "page_id": same[0]["id"]}

    if target is None:
        created = _create_page_by_id(base_url, headers, space_id, parent_id, title, storage)
        if "error" in created:
            return created
        failed = _write_owner(base_url, headers, created["page_id"], owner, None)
        if failed:
            # Unmarked, the page would block the next run as title_conflict: say so precisely.
            return {**failed, "error": f"ownership marker not saved: {failed['error']}",
                    "page_id": created["page_id"], "url": created["url"]}
        result = {"action": "created", **created}
        warning = _add_label(base_url, headers, created["page_id"])
        return {**result, "warning": warning} if warning else result

    page_id = target["page_id"]
    page = target["page"] or _get_page(base_url, headers, page_id)
    if "error" in page:
        return page
    if page.get("status") in _GONE_STATUSES:
        return _gone_error(page_id, page["status"])
    updated = _put_page(base_url, headers, page_id, page, title, storage)
    if "error" in updated:
        return updated
    result = {"action": "updated", **updated}
    warnings = []
    if not target["state"]["exact"]:  # adopted marker of another project_id
        failed = _write_owner(base_url, headers, page_id, owner, target["state"]["property"])
        if failed:
            warnings.append(f"ownership marker not updated: {failed['error']}")
    label = _add_label(base_url, headers, page_id)
    if label:
        warnings.append(label)
    return {**result, "warning": "; ".join(warnings)} if warnings else result


def _read_error(exc: Exception) -> str:
    """OSError text as before; a decode error by type only, like Notion's per-file error."""
    return str(exc) if isinstance(exc, OSError) else f"{type(exc).__name__}: could not read document"


def flow_attachment_plan(feature_dir: Path) -> dict[str, Any] | None:
    """FLOW.drawio attachment outcome before upload: None without one, `planned`, or `skipped`
    with the reason. Shared by sync_feature and the publish dry-run (REVIEW R3-2)."""
    flow = feature_dir / "FLOW.drawio"
    if not (flow.is_file() or flow.is_symlink()):
        return None
    reason = attachment_blocked_reason(flow, feature_dir)
    return ({"file": flow.name, "status": "skipped", "error": reason} if reason
            else {"file": flow.name, "status": "planned"})


def sync_feature(
    space_key: str,
    parent_title: str,
    feature_name: str,
    overview: bool = True,
    attach_flow: bool = True,
    root: str | None = None,
) -> dict[str, Any]:
    """Upload a feature's docs to Confluence.

    With `overview` (default) a feature page titled `feature_name` is created under
    `parent_title` first — review requests, summary, scope, API summary and the flow as text —
    and every .md becomes a child of that page; FLOW.drawio is attached to it when
    `attach_flow`. Without `overview` the .md pages go directly under `parent_title`
    (the pre-2026-10-27 behaviour). `feature_name` may carry a `<type>/` prefix.
    Returns {"feature", "overview", "attachments", "results": [{"file", "status", "url"|"error"}]}.
    Continues on per-file errors — partial results are always returned. A symlinked or
    outside .md/FLOW.drawio, or one with a high-confidence secret pattern, is not sent:
    it is reported as `status: "skipped"` with the reason (pattern kind only) in `error`.
    """
    # `root`: project path or registered project_id; omitted → the active target.
    project_root = resolve_project_dir(root) if root else target_project_root()
    if project_root is None:
        return {"error": "No active project. Run project_init, project_use, or pass root."}

    # Same name and symlink/escape checks as publish_feature and Notion (SECURITY L-3).
    try:
        _, feature_dir = feature_location(feature_name, project_root.resolve())
    except ValueError as exc:
        return {"error": str(exc)}
    if not feature_dir.is_dir():
        return {"error": f"Feature directory not found: {feature_dir}"}

    if not any(feature_dir.glob("*.md")):
        return {"feature": feature_name, "results": [], "warning": f"No .md files found in {feature_dir}"}

    # Symlinked/outside .md and ones with a secret pattern are skipped, as the dry-run reports
    # (DECISIONS ADR-011, ADR-012). Ordinary files keep the previous output.
    md_files, skipped = publishable_files(feature_dir)
    results: list[dict[str, Any]] = [{"file": name, "status": "skipped", "error": reason} for name, reason in skipped]
    if not md_files:
        # Nothing publishable (REVIEW R3-1): no remote call, no empty overview page.
        return {"feature": feature_name, "results": results, "warning": f"No publishable .md files in {feature_dir}"}

    ctx = _client_context("sync_feature")
    if isinstance(ctx, dict):
        return ctx
    base_url, headers = ctx
    space_id = _resolve_space_id(space_key, base_url, headers)
    if isinstance(space_id, dict):
        return space_id
    parent_id = _resolve_page_id(parent_title, space_id, base_url, headers)
    if isinstance(parent_id, dict):
        return parent_id

    overview_result: dict[str, Any] | None = None
    attachments: list[dict[str, Any]] = []
    children_parent = parent_id
    if overview:
        title = feature_name.rsplit("/", 1)[-1]
        try:
            body = _markdown_to_storage(build_overview_markdown(title, feature_dir, documents=md_files))
        except (OSError, UnicodeDecodeError) as exc:  # e.g. a non-UTF-8 PRD.md (REVIEW R3-4)
            created = {"error": _read_error(exc)}
        else:
            created = _create_page_by_id(base_url, headers, space_id, parent_id, title, body)
        if "error" in created:
            overview_result = {"title": title, "status": "error", "error": created["error"]}
        else:
            overview_result = {"title": title, "status": "created", "page_id": created["page_id"], "url": created["url"]}
            children_parent = created["page_id"]
            plan = flow_attachment_plan(feature_dir) if attach_flow else None
            if plan is not None:
                attachments.append(plan if plan["status"] == "skipped"
                                   else _upload_attachment(base_url, headers, created["page_id"], feature_dir / plan["file"]))

    for md_file in md_files:
        try:
            body_md = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:  # Never raises (REVIEW R3-4)
            results.append({"file": md_file.name, "status": "error", "error": _read_error(exc)})
            continue
        reason = secret_scan.skip_reason(body_md)  # changed since the listing scan
        if reason:
            results.append({"file": md_file.name, "status": "skipped", "error": reason})
            continue

        outcome = _create_page_by_id(base_url, headers, space_id, children_parent, md_file.stem, _markdown_to_storage(body_md))
        if "error" in outcome:
            results.append({"file": md_file.name, "status": "error", "error": outcome["error"]})
        else:
            results.append({"file": md_file.name, "status": "created", "url": outcome["url"]})

    results.sort(key=lambda r: r["file"])
    return {"feature": feature_name, "overview": overview_result, "attachments": attachments, "results": results}
