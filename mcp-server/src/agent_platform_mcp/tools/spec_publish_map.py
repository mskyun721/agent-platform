"""SPEC/INDEX publish building blocks shared by the Confluence and Notion clients.

* Ownership marker: `{"project_id", "slug"}` identifies a remote page this platform owns
  (BR-7). Confluence stores it as the content property `agent-platform` plus the label
  `agent-platform-spec`; Notion stores it as the first body block. Only a page with a
  matching marker is ever updated.
* PublishMap: `specs.<slug>` and `index` entries `{target, page_id, parent, project_path}` in
  the same ignored `.local/publish/<project_id>.json` the feature publisher uses, written
  under its lock (BR-16). `project_path` is the registered path (diagnostics only).

Nothing here makes a network call. Map helpers never raise; a save problem is a warning.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from agent_platform_mcp.tools import projects

OWNER_PROPERTY = "agent-platform"
OWNER_LABEL = "agent-platform-spec"
NOTION_MARKER_PREFIX = "agent-platform:"
INDEX_SLUG = "INDEX"  # owner slug of the generated INDEX page; never a valid SPEC slug (lowercase)
TARGETS = ("confluence", "notion")

_SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_CONFLUENCE_PAGE_ID_RE = re.compile(r"[1-9][0-9]{0,19}")

# A foreign marker with the same slug may be adopted when this returns True (e.g. its project_id
# is no longer registered after an ID change, AC-18). The caller decides; default is never.
AcceptOwner = Callable[[dict[str, str]], bool]


def owner_marker(project_id: Any, slug: Any) -> dict[str, str]:
    """Validated marker value; raises ValueError naming the bad field, never its value."""
    if not isinstance(project_id, str) or not projects.ID_RE.fullmatch(project_id):
        raise ValueError("invalid owner project_id")
    if not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug):
        raise ValueError("invalid owner slug")
    return {"project_id": project_id, "slug": slug}


def owner_matches(found: Any, owner: dict[str, str], accept_owner: AcceptOwner | None = None) -> bool:
    """Exact marker match, or a same-slug foreign marker the caller explicitly accepts."""
    if not isinstance(found, dict):
        return False
    value = {"project_id": found.get("project_id"), "slug": found.get("slug")}
    if value == owner:
        return True
    if accept_owner is None or value["slug"] != owner["slug"] or not isinstance(value["project_id"], str):
        return False
    return bool(accept_owner(dict(value)))


def notion_marker_text(owner: dict[str, str]) -> str:
    return f"{NOTION_MARKER_PREFIX}{owner['project_id']}/{owner['slug']}"


def parse_notion_marker(text: Any) -> dict[str, str] | None:
    if not isinstance(text, str) or not text.startswith(NOTION_MARKER_PREFIX):
        return None
    project_id, sep, slug = text[len(NOTION_MARKER_PREFIX):].strip().partition("/")
    try:
        return owner_marker(project_id, slug) if sep else None
    except ValueError:
        return None


def valid_confluence_page_id(value: Any) -> str | None:
    """Confluence page ids are positive decimal strings; anything else (paths, ?, /) → None."""
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    return value if isinstance(value, str) and _CONFLUENCE_PAGE_ID_RE.fullmatch(value) else None


def valid_page_id(target: str, value: Any) -> str | None:
    if target == "confluence":
        return valid_confluence_page_id(value)
    if target == "notion":
        return projects.normalize_notion_id(value)
    return None


# ---------------------------------------------------------------------------
# PublishMap: specs.<slug> / index
# ---------------------------------------------------------------------------

def _notion():
    # Lazy: notion imports this module for the marker helpers; the map I/O and lock live there.
    from agent_platform_mcp.tools import notion
    return notion


def registered_path(project_id: str | None) -> str | None:
    """Registry path of the project (not a worktree path), or None when unknown."""
    if project_id is None:
        return None
    try:
        context = projects.resolve(project_id)
    except (RuntimeError, ValueError, OSError):
        return None
    return str(context.path) if context.project_id == project_id else None


def _slot(data: dict[str, Any], slug: str | None) -> tuple[dict[str, Any], str]:
    """(container, key) of the entry: data["specs"][slug] or data["index"]."""
    if slug is None:
        return data, "index"
    specs = data.get("specs")
    if not isinstance(specs, dict):
        specs = data["specs"] = {}
    return specs, slug


def load_entry(project_id: str | None, slug: str | None, *, target: str, parent: str) -> dict[str, Any] | None:
    """Stored entry when it was published to the same target and parent with a well-formed page id;
    otherwise None (the owner search then reconnects or creates). `slug=None` is the INDEX page."""
    if slug is not None and not _SLUG_RE.fullmatch(slug):
        return None
    data = _notion()._load_map(project_id)
    container, key = _slot(dict(data), slug)
    entry = container.get(key)
    if (not isinstance(entry, dict) or entry.get("target") != target or entry.get("parent") != parent
            or valid_page_id(target, entry.get("page_id")) is None):
        return None
    return dict(entry)


def load_page_id(project_id: str | None, slug: str | None, *, target: str, parent: str) -> str | None:
    entry = load_entry(project_id, slug, target=target, parent=parent)
    return valid_page_id(target, entry["page_id"]) if entry else None


def save_entry(project_id: str | None, slug: str | None, *, target: str, page_id: str,
               parent: str) -> str | None:
    """Merge one entry under the publish-map lock; returns a warning instead of raising."""
    if project_id is None:
        return None
    if target not in TARGETS or valid_page_id(target, page_id) is None:
        return "publish map not saved: invalid page id"
    if slug is not None and not _SLUG_RE.fullmatch(slug):
        return "publish map not saved: invalid slug"
    entry = {"target": target, "page_id": valid_page_id(target, page_id), "parent": parent,
             "project_path": registered_path(project_id)}

    def put(data: dict[str, Any]) -> None:
        container, key = _slot(data, slug)
        container[key] = entry

    return _notion()._update_map(project_id, put)
