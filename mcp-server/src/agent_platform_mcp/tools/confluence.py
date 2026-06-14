"""Confluence Cloud REST API v2 tools."""

from __future__ import annotations

import base64
import html
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx

from agent_platform_mcp.config import ConfigError, confluence_config, docs_dir, target_project_root

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

_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n?", re.DOTALL)


def _strip_frontmatter(text: str) -> str:
    """Remove leading YAML frontmatter block (---...---) if present."""
    stripped = _FRONTMATTER_RE.sub("", text, count=1)
    return stripped.lstrip("\n")


def _inline(text: str) -> str:
    """Apply inline Markdown → HTML transformations to a single line of text."""
    # Escape HTML entities first to protect user content
    result = html.escape(text)
    # Bold before italic to avoid partial consumption of **
    result = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", result)
    result = re.sub(r"__(.+?)__", r"<strong>\1</strong>", result)
    # Italic — negative lookaround prevents matching inside **bold**
    result = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", result)
    result = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<em>\1</em>", result)
    # Inline code
    result = re.sub(r"`([^`]+)`", r"<code>\1</code>", result)
    # Links
    result = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', result)
    return result


def _markdown_to_storage(md: str) -> str:
    """Convert Markdown text to Confluence storage format (XML/HTML subset)."""
    text = _strip_frontmatter(md)
    lines = text.split("\n")

    parts: list[str] = []
    in_code = False
    code_lang = ""
    code_lines: list[str] = []
    in_ul = False
    in_ol = False
    para_lines: list[str] = []

    def flush_list() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            parts.append("</ul>")
            in_ul = False
        if in_ol:
            parts.append("</ol>")
            in_ol = False

    def flush_para() -> None:
        nonlocal para_lines
        if para_lines:
            parts.append(f"<p>{'<br />'.join(para_lines)}</p>")
            para_lines = []

    for line in lines:
        # --- Code block handling ---
        if in_code:
            if line.strip() == "```":
                body = "\n".join(code_lines)
                lang_param = f'<ac:parameter ac:name="language">{html.escape(code_lang)}</ac:parameter>' if code_lang else ""
                parts.append(
                    f'<ac:structured-macro ac:name="code">'
                    f"{lang_param}"
                    f"<ac:plain-text-body><![CDATA[{body}]]></ac:plain-text-body>"
                    f"</ac:structured-macro>"
                )
                in_code = False
                code_lines = []
                code_lang = ""
            else:
                code_lines.append(line)
            continue

        m_fence = re.match(r"^```(\w*)$", line.strip())
        if m_fence:
            flush_list()
            flush_para()
            in_code = True
            code_lang = m_fence.group(1)
            continue

        # --- Heading ---
        m_heading = re.match(r"^(#{1,6})\s+(.*)", line)
        if m_heading:
            flush_list()
            flush_para()
            level = len(m_heading.group(1))
            parts.append(f"<h{level}>{_inline(m_heading.group(2))}</h{level}>")
            continue

        # --- Horizontal rule ---
        if line.strip() in ("---", "***", "___"):
            flush_list()
            flush_para()
            parts.append("<hr />")
            continue

        # --- Unordered list ---
        m_ul = re.match(r"^[-*]\s+(.*)", line)
        if m_ul:
            flush_para()
            if in_ol:
                parts.append("</ol>")
                in_ol = False
            if not in_ul:
                parts.append("<ul>")
                in_ul = True
            parts.append(f"<li>{_inline(m_ul.group(1))}</li>")
            continue

        # --- Ordered list ---
        m_ol = re.match(r"^\d+\.\s+(.*)", line)
        if m_ol:
            flush_para()
            if in_ul:
                parts.append("</ul>")
                in_ul = False
            if not in_ol:
                parts.append("<ol>")
                in_ol = True
            parts.append(f"<li>{_inline(m_ol.group(1))}</li>")
            continue

        # --- Blank line ---
        if line.strip() == "":
            flush_list()
            flush_para()
            continue

        # --- Regular paragraph text ---
        flush_list()
        para_lines.append(_inline(line))

    # Flush any remaining open state
    if in_code and code_lines:
        body = "\n".join(code_lines)
        parts.append(f"<p><code>{'<br />'.join(html.escape(l) for l in code_lines)}</code></p>")
    flush_list()
    flush_para()

    return "\n".join(parts)


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

    post_headers = {**headers, "Content-Type": "application/json"}

    space_id = _resolve_space_id(space_key, base_url, headers)
    if isinstance(space_id, dict):
        return space_id

    parent_id = _resolve_page_id(parent_title, space_id, base_url, headers)
    if isinstance(parent_id, dict):
        return parent_id

    storage_body = _markdown_to_storage(body_markdown)

    payload = {
        "spaceId": space_id,
        "parentId": parent_id,
        "title": title,
        "status": "current",
        "body": {
            "representation": "storage",
            "value": storage_body,
        },
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


def sync_feature(
    space_key: str,
    parent_title: str,
    feature_name: str,
) -> dict[str, Any]:
    """Upload all .md files from docs/<type>/<feature_name>/ as Confluence pages.

    `feature_name` may include a `<type>/` prefix (e.g. "fix/login-bug" ->
    docs/fix/login-bug); a bare name defaults to docs/features/<feature_name>.
    Reads from the active target project (TARGET_PROJECT_ROOT or .active-project).
    Each file is created as a child of parent_title in the given space.
    Returns {"feature", "results": [{"file", "status", "url"|"error"}]}.
    Continues on per-file errors — partial results are always returned.
    """
    project_root = target_project_root()
    if project_root is None:
        return {"error": "No active project. Run project_init or set TARGET_PROJECT_ROOT."}

    feature_dir = docs_dir(feature_name, project_dir=project_root)
    if not feature_dir.is_dir():
        return {"error": f"Feature directory not found: {feature_dir}"}

    md_files = sorted(feature_dir.glob("*.md"))
    if not md_files:
        return {"feature": feature_name, "results": [], "warning": f"No .md files found in {feature_dir}"}

    results: list[dict[str, Any]] = []
    for md_file in md_files:
        try:
            body = md_file.read_text(encoding="utf-8")
        except OSError as exc:
            results.append({"file": md_file.name, "status": "error", "error": str(exc)})
            continue

        outcome = create_page(
            space_key=space_key,
            parent_title=parent_title,
            title=md_file.stem,
            body_markdown=body,
        )

        if "error" in outcome:
            results.append({"file": md_file.name, "status": "error", "error": outcome["error"]})
        else:
            results.append({"file": md_file.name, "status": "created", "url": outcome["url"]})

    return {"feature": feature_name, "results": results}
