"""Publish one SPEC (`docs/specs/<slug>/SPEC.md`) or the remote INDEX page (BR-6, BR-7, BR-8).

Only runs when called explicitly (`publish_spec` MCP tool, `publish --spec/--spec-index` CLI);
handoff and gate never publish. The project's `publish.target` decides where: none (also an
unregistered project) is `skipped` with no remote call. Before any remote call the document is
read once more, symlinks/escapes are refused and the exact text that would be sent is scanned for
secrets; a hit is `skipped` with the pattern kind only (Security I-6). Only `status: approved`
SPECs go out unless `allow_draft`; their §6 history hides fix/·hotfix/ rows like the remote INDEX.
Pages are written by the owner-checked upserts (`confluence.upsert_owned_page`,
`notion.upsert_owned_page`): a same-title page without the marker is never overwritten, and a
marker of another project_id only when the user named it (`adopt_from`, registry `previous_ids`).
MCP callers go through `publish_spec_confirmed` (Security 4b M-2). Never raises: failures are
{"error"} dicts or `status: failed`.
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
_RESULT_KEYS = ("code", "http_status", "page_status", "page_id", "url", "found_project_id")
FOREIGN_OWNER = "foreign_owner"
CONFIRMATION_REQUIRED = "confirmation_required"
# Dry-run makes no remote call, so it cannot tell title_conflict, foreign_owner or an adoption.
OWNERSHIP_UNCHECKED = "not checked: dry-run makes no remote call (title_conflict, foreign_owner or adoption show at publish)"


def _invalid(message: str) -> dict[str, str]:
    return {"error": message, "code": "invalid_arguments"}


def _adoptable(project_id: str, adopt_from: str | None) -> list[str]:
    """Old IDs the user opted in to adopt: `adopt_from` plus the registry record's `previous_ids`.
    A registry problem leaves only the explicit `adopt_from` (no adoption by default)."""
    allowed = {adopt_from} if adopt_from else set()
    try:
        allowed.update(projects.previous_ids(project_id))
    except (RuntimeError, ValueError, OSError, KeyError, TypeError, AttributeError):
        pass
    allowed.discard(project_id)
    return sorted(allowed)


class _AdoptOld:
    """`accept_owner` policy (BR-16, AC-18; Review 4b M-2, Security 4b M-1): a same-slug marker of
    another project_id is adopted only when that ID is in `allowed` (the user's explicit opt-in)
    and is then reported as `adopted_from`. Any other foreign marker is remembered in `foreign` so
    the caller reports `foreign_owner`; it is never overwritten. Being unregistered on this machine
    is not consent: registries differ per machine."""

    def __init__(self, project_id: str, allowed: list[str]) -> None:
        self.project_id, self.allowed = project_id, frozenset(allowed)
        self.adopted: str | None = None
        self.foreign: str | None = None

    def __call__(self, found: dict[str, str]) -> bool:
        other = found.get("project_id")
        if not isinstance(other, str) or other == self.project_id:
            return False
        if other in self.allowed:
            self.adopted = other
            return True
        self.foreign = self.foreign or other
        return False


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
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n").removeprefix("\ufeff")
    except (OSError, UnicodeDecodeError) as exc:
        return None, {"reason": f"{type(exc).__name__}: could not read SPEC.md"}
    meta = frontmatter.parse(text) or {}
    title = meta.get("title") if isinstance(meta.get("title"), str) and meta["title"].strip() else slug
    if meta.get("status") != "approved" and not allow_draft:
        return None, {"reason": NOT_APPROVED, "code": "publish_draft"}
    # Same boundary as `frontmatter.parse` (Security 4b L-1): front-matter never reaches the page.
    body = markdown_blocks.strip_frontmatter(text)
    try:
        return title.strip(), spec.remote_history(body)
    except spec.SpecError as exc:
        return None, {"reason": str(exc), "code": exc.code}


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


def _failed(key: str, project_id: str, target: str, outcome: dict[str, Any], accept: _AdoptOld) -> dict[str, Any]:
    if outcome.get("code") == "title_conflict" and accept.foreign:  # a marker the user did not opt in to
        outcome = {**outcome, "code": FOREIGN_OWNER, "found_project_id": accept.foreign,
                   "error": (f"page '{outcome.get('title')}' is owned by project_id {accept.foreign}; "
                             f"pass --adopt-from {accept.foreign} to take it over")}
    return _result(key, project_id, target, "failed", reason=outcome["error"],
                   result={k: outcome[k] for k in _RESULT_KEYS if k in outcome} or None)


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
                 dry_run: bool = False, root: str | None = None, adopt_from: str | None = None) -> dict[str, Any]:
    """Publish `docs/specs/<slug>/SPEC.md` or (index=True) the remote INDEX page.

    `adopt_from` names an old project_id whose same-slug marker may be taken over (also any
    `previous_ids` of the registry record). Returns PublishResult {feature: "specs/<slug>"|
    "specs/INDEX", project_id, target, status, reason, result} with status skipped (target none,
    draft, secret, symlink, missing, unreadable history) | planned (dry_run) | published | failed
    (title_conflict, foreign_owner {found_project_id}, ...), or {"error", "code"?} before any work.
    """
    if (slug is None) == (not index):
        return _invalid("pass exactly one of slug or index")
    if index and allow_draft:
        return _invalid("allow_draft applies to a SPEC, not the INDEX")
    if adopt_from is not None and (not isinstance(adopt_from, str) or not projects.ID_RE.fullmatch(adopt_from)):
        return _invalid("adopt_from must be a project_id")
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
    allowed = _adoptable(project_id, adopt_from)
    if dry_run:
        where = (settings["confluence"] if target == "confluence"
                 else {"parent_page_id": settings["notion"]["parent_page_id"]})
        plan = {"title": title, "dry_run": True, **where, "ownership": OWNERSHIP_UNCHECKED}
        return _result(key, project_id, target, "planned",
                       result={**plan, "may_adopt": allowed} if allowed else plan)

    owner = pmap.owner_marker(project_id, slug or pmap.INDEX_SLUG)
    accept = _AdoptOld(project_id, allowed)
    outcome = _upsert(target, settings, project_id, slug, title, body, owner, accept)
    if "error" in outcome:
        return _failed(key, project_id, target, outcome, accept)
    published = {k: outcome[k] for k in ("page_id", "url", "action", "version", "warning") if k in outcome}
    if accept.adopted:
        published["adopted_from"] = accept.adopted
    return _result(key, project_id, target, "published", result=published)


def publish_spec_confirmed(slug: str | None = None, index: bool = False, allow_draft: bool = False,
                           dry_run: bool = False, root: str | None = None, adopt_from: str | None = None,
                           confirm: bool = False) -> dict[str, Any]:
    """MCP entry (Security 4b M-2): a publish that changes a remote page, and any `allow_draft`
    call, needs `confirm=True`. Without it nothing is sent: the dry-run plan comes back with status
    `confirmation_required` (what would go where), or the dry-run's own skipped/error result.
    A plain dry-run needs no confirmation. The CLI is a human action and calls `publish_spec`."""
    kwargs = {"slug": slug, "index": index, "allow_draft": allow_draft, "root": root, "adopt_from": adopt_from}
    if confirm is True or (dry_run and not allow_draft):
        return publish_spec(dry_run=dry_run, **kwargs)
    plan = publish_spec(dry_run=True, **kwargs)
    if plan.get("status") != "planned":
        return plan
    what = "a draft SPEC" if allow_draft else "this page"
    return {**plan, "status": CONFIRMATION_REQUIRED,
            "reason": f"publishing {what} creates or replaces a remote page; call again with confirm=true "
                      "only after the user agreed",
            "result": {**plan["result"], "dry_run": dry_run, "allow_draft": allow_draft,
                       **({"adopt_from": adopt_from} if adopt_from else {})}}
