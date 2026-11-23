"""Publish one SPEC (`docs/specs/<slug>/SPEC.md`) or the remote INDEX page (BR-6, BR-7, BR-8).

Only runs when called explicitly (`publish_spec` MCP tool, `publish --spec/--spec-index` CLI);
handoff and gate never publish. The project's `publish.target` decides where: none (also an
unregistered project) is `skipped` with no remote call. Before any remote call the document is
read once more, symlinks/escapes are refused and the exact text that would be sent is scanned for
secrets; a hit is `skipped` with the pattern kind only (Security I-6). Only `status: approved`
SPECs go out unless `allow_draft`. Pages are written by the owner-checked upserts
(`confluence.upsert_owned_page`, `notion.upsert_owned_page`): a same-title page without the
marker is never overwritten. Never raises: failures are {"error"} dicts or `status: failed`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_platform_mcp import frontmatter, markdown_blocks, secret_scan
from agent_platform_mcp.tools import confluence as confluence_tools
from agent_platform_mcp.tools import notion, projects, spec
from agent_platform_mcp.tools import spec_publish_map as pmap
from agent_platform_mcp.tools.feature import safe_path
from agent_platform_mcp.tools.publish import _result

INDEX_KEY = "specs/INDEX"
NOT_APPROVED = "spec is not approved"
OUTSIDE = "symlink or outside spec directory"
_RESULT_KEYS = ("code", "http_status", "page_status", "page_id", "url")


def _invalid(message: str) -> dict[str, str]:
    return {"error": message, "code": "invalid_arguments"}


def _registered(project_id: str) -> bool:
    """True when `project_id` is in the registry; a registry problem counts as registered (no adoption)."""
    try:
        return any(entry["project_id"] == project_id for entry in projects.list_projects()["projects"])
    except (RuntimeError, ValueError, OSError, KeyError, TypeError):
        return True


class _AdoptOld:
    """`accept_owner` policy (BR-16, AC-18): a same-slug marker whose project_id is no longer
    registered (the project was re-registered under a new ID) is adopted and reported as
    `adopted_from`. A marker of a registered project, or of this project, is never adopted.
    The marker is not tied to its author (Security L-1), so adoption grants an editor nothing
    they could not already do by editing the page; it is always reported, never silent."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self.adopted: str | None = None

    def __call__(self, found: dict[str, str]) -> bool:
        other = found.get("project_id")
        if not isinstance(other, str) or other == self.project_id or _registered(other):
            return False
        self.adopted = other
        return True


def _spec_document(project: Path, slug: str, allow_draft: bool) -> tuple[str, str] | tuple[None, dict]:
    """(title, markdown) of an approved SPEC, or (None, {"reason", "code"?}) to skip it."""
    path = project.joinpath(*spec.SPECS_DIR, slug, spec.SPEC_FILE)
    try:
        safe_path(path, project)  # no symlink from docs/ down to SPEC.md
    except ValueError:
        return None, {"reason": OUTSIDE}
    if not path.is_file() or not path.resolve().is_relative_to(project.resolve()):
        return None, {"reason": f"spec not found: {slug}", "code": "spec_not_found"}
    try:
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError) as exc:
        return None, {"reason": f"{type(exc).__name__}: could not read SPEC.md"}
    meta = frontmatter.parse(text) or {}
    title = meta.get("title") if isinstance(meta.get("title"), str) and meta["title"].strip() else slug
    if meta.get("status") != "approved" and not allow_draft:
        return None, {"reason": NOT_APPROVED, "code": "publish_draft"}
    return title.strip(), markdown_blocks.strip_frontmatter(text)


def _index_document(project: Path, project_id: str) -> tuple[str, str] | tuple[None, dict]:
    """(title, markdown) of the remote INDEX (fix/·hotfix/ hidden, N-1 cells dropped)."""
    if not project.joinpath(*spec.SPECS_DIR).is_dir():
        return None, {"reason": "no docs/specs directory", "code": "spec_not_found"}
    try:
        text, _counts = spec.index_markdown(project, remote=True)
    except ValueError:  # a symlinked docs/specs
        return None, {"reason": OUTSIDE}
    except OSError as exc:
        return None, {"reason": f"{type(exc).__name__}: could not build INDEX"}
    lines = text.split("\n")
    if lines and lines[0] == spec.INDEX_MARK:  # an HTML comment turns into visible text remotely
        lines = lines[1:]
    return f"{project_id} 기능 목록", "\n".join(lines)


def _upsert(target: str, settings: dict, project_id: str, slot: str | None, title: str,
            body: str, owner: dict[str, str], accept: _AdoptOld) -> dict[str, Any]:
    if target == "notion":
        parent = projects.normalize_notion_id(settings["notion"]["parent_page_id"])
        known = pmap.load_page_id(project_id, slot, target="notion", parent=parent)
        result = notion.upsert_owned_page(parent, title, body, owner, known_page_id=known, accept_owner=accept)
        if "error" not in result:
            warning = pmap.save_entry(project_id, slot, target="notion", page_id=result["page_id"], parent=parent)
            if warning:
                result = {**result, "warning": "; ".join(w for w in (result.get("warning"), warning) if w)}
        return result
    # Confluence reads and writes the map itself: only it knows the resolved parent page id.
    conf = settings["confluence"]
    return confluence_tools.upsert_owned_page(conf["space_key"], conf["parent_title"], title, body, owner,
                                              accept_owner=accept)


def publish_spec(slug: str | None = None, index: bool = False, allow_draft: bool = False,
                 dry_run: bool = False, root: str | None = None) -> dict[str, Any]:
    """Publish `docs/specs/<slug>/SPEC.md` or (index=True) the remote INDEX page.

    Returns PublishResult {feature: "specs/<slug>"|"specs/INDEX", project_id, target, status, reason,
    result} with status skipped (target none, draft, secret, symlink, missing) | planned (dry_run)
    | published | failed, or {"error", "code"?} before any work.
    """
    if (slug is None) == (not index):
        return _invalid("pass exactly one of slug or index")
    if index and allow_draft:
        return _invalid("allow_draft applies to a SPEC, not the INDEX")
    try:
        if slug is not None:
            spec.validate_slug(slug)
        context = projects.resolve(root)
        settings = projects.get_publish(context.project_id)
    except spec.SpecError as exc:
        return {"error": str(exc), "code": exc.code}
    except (RuntimeError, ValueError, OSError) as exc:  # no target, unknown root, InvalidSettings
        return {"error": str(exc)}
    key = f"specs/{slug}" if slug else INDEX_KEY
    project_id, target = context.project_id, (settings or {}).get("target", "none")
    if target == "none":
        return _result(key, project_id, "none", "skipped", reason="publish target is none")

    title, body = (_spec_document(context.path, slug, allow_draft) if slug
                   else _index_document(context.path, project_id))
    if title is None:
        skipped = body
        return _result(key, project_id, target, "skipped", reason=skipped["reason"],
                       result={"code": skipped["code"]} if "code" in skipped else None)
    # The exact text that would leave the machine, title included, read just now (Security I-6).
    reason = secret_scan.skip_reason(f"{title}\n{body}")
    if reason:
        return _result(key, project_id, target, "skipped", reason=reason, result={"code": "secret_detected"})
    if dry_run:
        where = (settings["confluence"] if target == "confluence"
                 else {"parent_page_id": settings["notion"]["parent_page_id"]})
        return _result(key, project_id, target, "planned", result={"title": title, "dry_run": True, **where})

    owner = pmap.owner_marker(project_id, slug or pmap.INDEX_SLUG)
    accept = _AdoptOld(project_id)
    outcome = _upsert(target, settings, project_id, slug, title, body, owner, accept)
    if "error" in outcome:
        return _result(key, project_id, target, "failed", reason=outcome["error"],
                       result={k: outcome[k] for k in _RESULT_KEYS if k in outcome} or None)
    published = {k: outcome[k] for k in ("page_id", "url", "action", "version", "warning") if k in outcome}
    if accept.adopted:
        published["adopted_from"] = accept.adopted
    return _result(key, project_id, target, "published", result=published)
