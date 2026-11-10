"""Confluence Cloud REST API v2 tools."""

from __future__ import annotations

import base64
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx

from agent_platform_mcp import markdown_blocks
from agent_platform_mcp.config import ConfigError, confluence_config, docs_dir, resolve_project_dir, target_project_root

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

    if resp.status_code == 401:
        return {"error": "Confluence auth failed. Check CONFLUENCE_EMAIL / CONFLUENCE_API_TOKEN"}
    if resp.status_code != 200:
        return {"error": f"Confluence API error: HTTP {resp.status_code}"}

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

    if resp.status_code == 401:
        return {"error": "Confluence auth failed. Check CONFLUENCE_EMAIL / CONFLUENCE_API_TOKEN"}
    if resp.status_code != 200:
        return {"error": f"Confluence API error: HTTP {resp.status_code}"}

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
        return {"error": "Confluence auth failed. Check CONFLUENCE_EMAIL / CONFLUENCE_API_TOKEN"}

    if resp.status_code == 400:
        try:
            detail = resp.json()
            errors = detail.get("errors", [])
            msg = errors[0].get("title", "Bad request") if errors else "Bad request"
        except (ValueError, IndexError, KeyError):
            msg = "Bad request"
        return {"error": f"Confluence rejected page creation: {msg}"}

    if resp.status_code not in (200, 201):
        return {"error": f"Confluence API error: HTTP {resp.status_code}"}

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


def update_page(page_id: str, body_markdown: str, title: str = "") -> dict[str, Any]:
    """Replace the body of an existing page (or draft) by ID with converted Markdown.

    An empty title keeps the current one; an untitled draft needs a title.
    Returns {"title", "page_id", "url", "version"} on success, or {"error": "..."}.
    """
    ctx = _client_context("update_page")
    if isinstance(ctx, dict):
        return ctx
    base_url, headers = ctx

    try:
        cur = httpx.get(f"{base_url}/wiki/api/v2/pages/{page_id}", headers=headers, timeout=DEFAULT_TIMEOUT_SEC)
    except httpx.RequestError:
        return {"error": f"Confluence request timed out after {DEFAULT_TIMEOUT_SEC}s"}
    if cur.status_code == 401:
        return {"error": "Confluence auth failed. Check CONFLUENCE_EMAIL / CONFLUENCE_API_TOKEN"}
    if cur.status_code == 404:
        return {"error": f"Page {page_id} not found"}
    if cur.status_code != 200:
        return {"error": f"Confluence API error: HTTP {cur.status_code}"}
    try:
        data = cur.json()
    except ValueError:
        return {"error": "Confluence returned a non-JSON response"}

    new_title = title or data.get("title", "")
    if not new_title:
        return {"error": "Page has no title; pass title"}
    version = int(data.get("version", {}).get("number", 0)) + 1
    payload = {
        "id": page_id,
        "status": "current",
        "title": new_title,
        "body": {"representation": "storage", "value": _markdown_to_storage(body_markdown)},
        "version": {"number": version},
    }
    try:
        resp = httpx.put(
            f"{base_url}/wiki/api/v2/pages/{page_id}",
            json=payload,
            headers={**headers, "Content-Type": "application/json"},
            timeout=DEFAULT_TIMEOUT_SEC,
        )
    except httpx.RequestError:
        return {"error": f"Confluence request timed out after {DEFAULT_TIMEOUT_SEC}s"}
    if resp.status_code not in (200, 201):
        return {"error": f"Confluence API error: HTTP {resp.status_code}"}
    space_id = data.get("spaceId", "")
    return {
        "title": new_title,
        "page_id": page_id,
        "url": f"{base_url}/wiki/spaces/{space_id}/pages/{page_id}",
        "version": version,
    }


# Sections of the PRD a reviewer reads first; everything else stays on the PRD child page.
_OVERVIEW_SECTION_KEYWORDS = ("검토 요청", "개요", "범위", "API 요약", "처리 흐름")


def build_overview_markdown(feature_name: str, feature_dir: Path) -> str:
    """Feature overview page: review requests, summary, scope, API summary, flow (Mermaid text
    from FLOW.drawio) and links to the document pages. Built from the PRD so the Confluence
    page and the local REVIEW-VIEW.html say the same thing."""
    from agent_platform_mcp.tools.feature_view import drawio_to_mermaid

    prd = feature_dir / "PRD.md"
    out: list[str] = [f"# {feature_name}", ""]
    if prd.is_file():
        blocks = markdown_blocks.parse(prd.read_text(encoding="utf-8"))
        for section in markdown_blocks.sections(blocks):
            if section["level"] == 2 and any(k in section["title"] for k in _OVERVIEW_SECTION_KEYWORDS):
                out.append(f"## {section['title']}")
                out.append(_blocks_to_markdown(section["blocks"]))
                out.append("")
    else:
        out.append("_PRD.md 없음_\n")
    flow = feature_dir / "FLOW.drawio"
    if flow.is_file():
        try:
            graphs = drawio_to_mermaid(flow.read_text(encoding="utf-8"))
        except ET.ParseError:
            graphs = []
        if graphs:
            out.append("## 서비스 흐름 (FLOW.drawio 텍스트 뷰)")
            out.append("원본 FLOW.drawio 는 이 페이지에 첨부된다. 편집은 draw.io 로.")
            out.extend(f"```mermaid\n{g}\n```" for g in graphs)
            out.append("")
    out.append("## 문서")
    out.extend(f"- {p.stem}" for p in sorted(feature_dir.glob("*.md")))
    out.append("")
    return "\n".join(out)


def _blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    """Round-trip parsed blocks back to Markdown (enough for the PRD's own vocabulary)."""
    out: list[str] = []
    for block in blocks:
        kind = block["type"]
        if kind == "heading":
            out.append(f"{'#' * block['level']} {block['text']}")
        elif kind == "para":
            out.append("\n".join(block["lines"]))
        elif kind == "ul":
            out.extend(f"- {i}" for i in block["items"])
        elif kind == "ol":
            out.extend(f"{n}. {i}" for n, i in enumerate(block["items"], 1))
        elif kind == "tasks":
            out.extend(f"- [{'x' if d else ' '}] {t}" for d, t in block["items"])
        elif kind == "code":
            out.append(f"```{block['lang']}\n{block['body']}\n```")
        elif kind == "table":
            out.append("| " + " | ".join(block["header"]) + " |")
            out.append("|" + "---|" * len(block["header"]))
            out.extend("| " + " | ".join(c.replace("|", "\\|") for c in row) + " |" for row in block["rows"])
        elif kind == "quote":
            out.extend(f"> {l}" for l in block["lines"])
        elif kind == "hr":
            out.append("---")
        out.append("")
    return "\n".join(out).rstrip()


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
    Continues on per-file errors — partial results are always returned.
    """
    # `root`: project path or registered project_id; omitted → the active target.
    project_root = resolve_project_dir(root) if root else target_project_root()
    if project_root is None:
        return {"error": "No active project. Run project_init, project_use, or pass root."}

    feature_dir = docs_dir(feature_name, project_dir=project_root)
    if not feature_dir.is_dir():
        return {"error": f"Feature directory not found: {feature_dir}"}

    md_files = sorted(feature_dir.glob("*.md"))
    if not md_files:
        return {"feature": feature_name, "results": [], "warning": f"No .md files found in {feature_dir}"}

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
        body = _markdown_to_storage(build_overview_markdown(title, feature_dir))
        created = _create_page_by_id(base_url, headers, space_id, parent_id, title, body)
        if "error" in created:
            overview_result = {"title": title, "status": "error", "error": created["error"]}
        else:
            overview_result = {"title": title, "status": "created", "page_id": created["page_id"], "url": created["url"]}
            children_parent = created["page_id"]
            flow = feature_dir / "FLOW.drawio"
            if attach_flow and flow.is_file():
                attachments.append(_upload_attachment(base_url, headers, created["page_id"], flow))

    results: list[dict[str, Any]] = []
    for md_file in md_files:
        try:
            body_md = md_file.read_text(encoding="utf-8")
        except OSError as exc:
            results.append({"file": md_file.name, "status": "error", "error": str(exc)})
            continue

        outcome = _create_page_by_id(base_url, headers, space_id, children_parent, md_file.stem, _markdown_to_storage(body_md))
        if "error" in outcome:
            results.append({"file": md_file.name, "status": "error", "error": outcome["error"]})
        else:
            results.append({"file": md_file.name, "status": "created", "url": outcome["url"]})

    return {"feature": feature_name, "overview": overview_result, "attachments": attachments, "results": results}
