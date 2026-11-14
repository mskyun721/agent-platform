"""Notion REST client and feature publisher (idempotent upsert).

Public functions never raise; failures come back as {"error": "..."} dicts and never carry
the token, response bodies or headers. The token is read from env only when a request is
about to be made, so importing this module or a dry run needs no configuration.

Page layout: parent page → overview page titled `<type>/<name>` → one child page per `*.md`
titled `file.stem`. Page IDs are remembered in ignored `.local/publish/<project_id>.json`;
when that is missing or stale the page is found again by exact title under its parent.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx

from agent_platform_mcp import config, markdown_blocks, notion_blocks, secret_scan
from agent_platform_mcp.config import ConfigError, notion_config
from agent_platform_mcp.tools import projects
from agent_platform_mcp.tools.feature_overview import build_overview_markdown, feature_location, publishable_files

try:
    import fcntl
except ImportError:  # Mapping is optional; publishing still works without it.
    fcntl = None

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
DEFAULT_TIMEOUT_SEC = 30
MAX_RETRIES = 3
DEFAULT_RETRY_WAIT_SEC = 1.0
MAX_RETRY_WAIT_SEC = 10.0
MAP_DIR = config.ROOT / ".local" / "publish"
_IDEMPOTENT = {"GET", "DELETE"}
# Blocks a page owns as sub-pages; clearing a body must never archive them.
_KEEP_ON_REPLACE = {"child_page", "child_database"}

_sleep = time.sleep  # patched in tests


class _NotionError(Exception):
    """Token-free failure message; `status` is the HTTP status when there was one."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _retry_wait(resp: httpx.Response) -> float:
    try:
        wait = float(resp.headers.get("Retry-After"))
    except (TypeError, ValueError):
        return DEFAULT_RETRY_WAIT_SEC
    if wait != wait or wait < 0:  # NaN or negative
        return DEFAULT_RETRY_WAIT_SEC
    return min(wait, MAX_RETRY_WAIT_SEC)


def _token() -> str:
    try:
        return notion_config()["token"]
    except ConfigError as exc:
        raise _NotionError(str(exc)) from None


def _call(token: str, method: str, path: str, *, json: Any = None, params: dict | None = None) -> dict:
    """One API call. 429 is always retried (Notion did not process it); 5xx only for
    idempotent methods, so a POST/PATCH that may have landed is never sent twice."""
    headers = {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION,
               "Content-Type": "application/json"}
    kwargs: dict[str, Any] = {"headers": headers, "timeout": DEFAULT_TIMEOUT_SEC}
    if json is not None:
        kwargs["json"] = json
    if params is not None:
        kwargs["params"] = params
    retries = 0
    while True:
        try:
            resp = httpx.request(method, f"{API_BASE}{path}", **kwargs)
        except httpx.TimeoutException:
            raise _NotionError(f"Notion request timed out after {DEFAULT_TIMEOUT_SEC}s") from None
        except (httpx.HTTPError, httpx.InvalidURL):
            raise _NotionError("Notion request failed") from None
        retryable = resp.status_code == 429 or (resp.status_code >= 500 and method in _IDEMPOTENT)
        if not retryable:
            break
        if retries == MAX_RETRIES:
            if resp.status_code == 429:
                raise _NotionError(f"Notion rate limited after {MAX_RETRIES} retries", 429)
            break
        retries += 1
        _sleep(_retry_wait(resp))
    status = resp.status_code
    if status in (200, 201):
        try:
            data = resp.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise _NotionError("Notion API returned an invalid response", status)
        return data
    if status == 401:
        raise _NotionError("Notion auth failed. Check NOTION_TOKEN", status)
    if status in (403, 404):
        raise _NotionError("Notion page not shared with integration or not found", status)
    code = None
    try:
        body = resp.json()
        code = body.get("code") if isinstance(body, dict) else None
    except ValueError:
        pass
    suffix = f" ({code})" if isinstance(code, str) and code.isidentifier() else ""
    raise _NotionError(f"Notion API error: HTTP {status}{suffix}", status)


# ---------------------------------------------------------------------------
# Page operations
# ---------------------------------------------------------------------------

def _children(token: str, block_id: str) -> list[dict]:
    found: list[dict] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        data = _call(token, "GET", f"/blocks/{block_id}/children", params=params)
        found += [r for r in data.get("results") or [] if isinstance(r, dict) and isinstance(r.get("id"), str)]
        cursor = data.get("next_cursor")
        if not data.get("has_more") or not cursor:
            return found


def _find_child_page(token: str, parent_id: str, title: str) -> str | None:
    for item in _children(token, parent_id):
        child = item.get("child_page")
        if item.get("type") == "child_page" and isinstance(child, dict) and child.get("title") == title:
            return item["id"]
    return None


def _page(token: str, page_id: str) -> dict | None:
    """Live page data, or None when the page is gone (404, archived or in trash)."""
    try:
        data = _call(token, "GET", f"/pages/{page_id}")
    except _NotionError as exc:
        if exc.status == 404:
            return None
        raise
    return None if data.get("archived") or data.get("in_trash") else data


def _append(token: str, block_id: str, items: list[dict]) -> None:
    """PATCH children 100 at a time; deferred grandchildren follow per parent block."""
    for chunk in notion_blocks.chunks(items):
        sent: list[dict] = []
        deferred: list[tuple[int, list[dict]]] = []
        for index, item in enumerate(chunk):
            item, rest = notion_blocks.split_block(item)
            if rest:
                deferred.append((index, rest))
            sent.append(item)
        data = _call(token, "PATCH", f"/blocks/{block_id}/children", json={"children": sent})
        results = data.get("results")
        for index, rest in deferred:
            try:
                child_id = results[index]["id"]
            except (TypeError, IndexError, KeyError):
                raise _NotionError("Notion append returned no block id") from None
            _append(token, child_id, rest)


def _create_page(token: str, parent_id: str, title: str, items: list[dict]) -> dict:
    head = min(len(items), notion_blocks.MAX_CHILDREN)
    head = next((n for n, b in enumerate(items[:head]) if notion_blocks.needs_deferral(b)), head)
    data = _call(token, "POST", "/pages", json={
        "parent": {"page_id": parent_id},
        "properties": {"title": {"title": notion_blocks.text_items(title[:notion_blocks.MAX_TEXT])}},
        "children": items[:head],
    })
    if not isinstance(data.get("id"), str) or not data["id"]:
        raise _NotionError("Notion page creation returned no id")
    _append(token, data["id"], items[head:])
    return data


def _replace_children(token: str, page_id: str, items: list[dict]) -> None:
    for item in _children(token, page_id):
        if item.get("type") not in _KEEP_ON_REPLACE:
            _call(token, "DELETE", f"/blocks/{item['id']}")
    _append(token, page_id, items)


def _url(data: dict | None, page_id: str) -> str:
    url = (data or {}).get("url")
    return url if isinstance(url, str) and url else f"https://www.notion.so/{page_id.replace('-', '')}"


def _upsert(token: str, parent_id: str, title: str, items: list[dict], known_id: str | None) -> dict:
    """Mapped page → title match under parent → create. Raises _NotionError."""
    data = _page(token, known_id) if known_id else None
    page_id = known_id if data else _find_child_page(token, parent_id, title)
    if page_id:
        _replace_children(token, page_id, items)
        return {"status": "updated", "page_id": page_id, "url": _url(data, page_id)}
    created = _create_page(token, parent_id, title, items)
    return {"status": "created", "page_id": created["id"], "url": _url(created, created["id"])}


# ---------------------------------------------------------------------------
# Page-ID mapping (.local/publish/<project_id>.json)
# ---------------------------------------------------------------------------

def _map_file(project_id: str) -> Path:
    return MAP_DIR / f"{project_id}.json"


def _load_map(project_id: str | None) -> dict[str, Any]:
    """Stored mapping, or an empty one when absent or damaged (title lookup recovers)."""
    empty: dict[str, Any] = {"schema": 1, "features": {}}
    if project_id is None:
        return empty
    path = _map_file(project_id)
    try:
        projects.safe_storage(path)
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict) or data.get("schema") != 1 or not isinstance(data.get("features"), dict):
        return empty
    return data


def _feature_map(mapping: dict[str, Any], key: str, parent_id: str) -> dict[str, Any]:
    """This feature's entry if it was published under the same parent; otherwise empty."""
    entry = mapping["features"].get(key)
    if (isinstance(entry, dict) and entry.get("parent") == parent_id
            and isinstance(entry.get("files"), dict)):
        return entry
    return {"parent": parent_id, "overview": None, "files": {}}


@contextmanager
def _map_lock(path: Path):
    if fcntl is None:
        yield
        return
    lock = path.with_suffix(".lock")
    projects.safe_storage(lock)
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("publish map is busy")
                time.sleep(0.05)
        yield
    finally:
        os.close(descriptor)


def _save_map(project_id: str | None, key: str, entry: dict[str, Any]) -> str | None:
    """Merge one feature entry under lock and replace the file atomically; returns a
    warning instead of raising so a mapping problem never hides a successful publish."""
    if project_id is None:
        return None
    path = _map_file(project_id)
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        projects.safe_storage(path)
        with _map_lock(path):
            data = _load_map(project_id)
            data["features"][key] = entry
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=f".{path.name}.", delete=False) as output:
                temporary = Path(output.name)
                json.dump(data, output, ensure_ascii=False, indent=2)
                output.write("\n")
            os.replace(temporary, path)
            temporary = None
    except (OSError, ValueError, TimeoutError) as exc:
        return f"publish map not saved: {type(exc).__name__}"
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return None


# ---------------------------------------------------------------------------
# Feature sync
# ---------------------------------------------------------------------------

NO_PROJECT = "No active project. Run project_init, project_use, or pass root."
NO_PUBLISHABLE = "No publishable .md files"


def locate_feature(feature_name: str, root: str | None) -> dict[str, Any]:
    """{"context", "key", "feature_dir"} inside the allowlisted project, or {"error"}."""
    try:
        context = projects.resolve(root)
        key, feature_dir = feature_location(feature_name, context.path)
    except RuntimeError as exc:  # no active target, or a path outside the allowlist
        return {"error": NO_PROJECT if "No active target project" in str(exc) else str(exc)}
    except (ValueError, FileNotFoundError) as exc:
        return {"error": str(exc)}
    if not feature_dir.is_dir():
        return {"error": f"Feature directory not found: {feature_dir}"}
    return {"context": context, "key": key, "feature_dir": feature_dir}


def feature_files(feature_dir: Path) -> tuple[list[Path], list[dict]]:
    """Publishable `*.md` and Notion `skipped` outcomes (outside path or secret pattern)."""
    files, skipped = publishable_files(feature_dir)
    return files, [_outcome(name, Path(name).stem, "skipped", error=reason) for name, reason in skipped]


def _outcome(file: str | None, title: str, status: str, page_id: str | None = None,
             url: str | None = None, error: str | None = None) -> dict[str, Any]:
    return {"file": file, "title": title, "status": status, "page_id": page_id, "url": url, "error": error}


def _blocks(markdown: str) -> list[dict]:
    return notion_blocks.render_notion(markdown_blocks.parse(markdown))


def sync_feature(feature_name: str, parent_page_id: str | None = None, root: str | None = None,
                 dry_run: bool = False) -> dict[str, Any]:
    """Publish docs/<type>/<name>/*.md to Notion under `parent_page_id` (or the project's
    `publish.notion.parent_page_id`). Refused unless the project's publish target is notion.
    Re-running updates the same pages. With no publishable .md, `overview` is None and nothing
    is sent (dry-run too). Never raises."""
    located = locate_feature(feature_name, root)
    if "error" in located:
        return located
    context, key, feature_dir = located["context"], located["key"], located["feature_dir"]

    # The project's chosen target gates every Notion publish, even with an explicit parent:
    # unregistered or unset means none (ADR-008), so a company project never reaches Notion.
    try:
        settings = projects.get_publish(context.project_id) or {}
    except ValueError as exc:  # InvalidSettings carries only the field name
        return {"error": str(exc)}
    target = settings.get("target", "none")
    if target != "notion":
        return {"error": f"project publish target is {target}; notion publish refused"}
    if parent_page_id is None:
        parent_page_id = settings["notion"]["parent_page_id"]
    parent = projects.normalize_notion_id(parent_page_id)
    if parent is None:
        return {"error": "Invalid parent_page_id"}

    files, skipped = feature_files(feature_dir)
    entry = _feature_map(_load_map(context.project_id), key, parent)
    result: dict[str, Any] = {"feature": key, "parent_page_id": parent, "dry_run": dry_run}
    if not files:
        # Nothing publishable (REVIEW R3-1): no empty overview page, dry-run or not.
        return {**result, "overview": None, "results": skipped, "warning": NO_PUBLISHABLE}

    if dry_run:
        def planned(file: str | None, title: str, known: str | None) -> dict:
            return _outcome(file, title, "planned_update" if known else "planned_create", page_id=known)

        result["overview"] = planned(None, key, entry["overview"])
        result["results"] = sorted([*(planned(p.name, p.stem, entry["files"].get(p.name)) for p in files), *skipped],
                                   key=lambda r: r["file"])
        return result

    try:
        token = _token()
    except _NotionError as exc:
        return {"error": str(exc)}

    try:
        overview_md = build_overview_markdown(key, feature_dir, attached_flow=False, documents=files)
        page = _upsert(token, parent, key, _blocks(overview_md), entry["overview"])
    except (_NotionError, OSError, ValueError) as exc:
        result["overview"] = _outcome(None, key, "error", error=_message(exc))
        result["results"] = []
        return result
    result["overview"] = _outcome(None, key, page["status"], page["page_id"], page["url"])
    if page["page_id"] != entry["overview"]:
        # Created or found again by title: child IDs of the previous overview belong to that page.
        entry["files"] = {}
    entry["overview"] = page["page_id"]

    results = list(skipped)
    for path in files:
        try:
            body = path.read_text(encoding="utf-8")
            reason = secret_scan.skip_reason(body)  # changed since the listing scan
            if reason:
                results.append(_outcome(path.name, path.stem, "skipped", error=reason))
                continue
            page = _upsert(token, entry["overview"], path.stem, _blocks(body), entry["files"].get(path.name))
        except (_NotionError, OSError, ValueError) as exc:
            results.append(_outcome(path.name, path.stem, "error", error=_message(exc)))
            continue
        entry["files"][path.name] = page["page_id"]
        results.append(_outcome(path.name, path.stem, page["status"], page["page_id"], page["url"]))
    result["results"] = sorted(results, key=lambda r: r["file"])
    warning = _save_map(context.project_id, key, entry)
    if warning:
        result["warning"] = warning
    return result


def _message(exc: Exception) -> str:
    """Token-free error text: our own messages verbatim, anything else by type only."""
    return str(exc) if isinstance(exc, _NotionError) else f"{type(exc).__name__}: could not read document"
