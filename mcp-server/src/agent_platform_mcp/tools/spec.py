"""Feature specs: the living `docs/specs/<slug>/SPEC.md` of a target project.

A SPEC is the current state of one feature (rules, API, DB, service logic and a
change-history table). Work items (`docs/<type>/<name>/`) link to it with a
`spec: <slug>` front-matter field in PRD.md or WORK.md, and are marked finished
with `archived: true`. Everything here reads front-matter and a few table rows
only and never calls an AI. Results are JSON dicts; failures are
`{"error", "code"?}`, never exceptions. Every write is atomic and refuses
symlinks and paths outside the spec / work-item directory (BR-15).
"""

from __future__ import annotations

import argparse
import functools
import os
import re
import tempfile
from datetime import date as date_type
from pathlib import Path
from typing import Any, Callable

from agent_platform_mcp import config, frontmatter
from agent_platform_mcp.config import AGENT_OUTPUTS_BY_TRACK, LIGHT_TRACK_PREFIXES
from agent_platform_mcp.tools import projects
from agent_platform_mcp.tools.feature import DATE_RE, NAME_SEGMENT, RESERVED_TYPES, ensure_safe_name, safe_path

SLUG_RE = re.compile(NAME_SEGMENT)
SPECS_DIR = ("docs", "specs")
SPEC_FILE = "SPEC.md"
PRIMARY_DOCS = ("WORK.md", "PRD.md")  # where a work item's `spec` / `archived` is read


class SpecError(ValueError):
    """A contract error with a stable code (PRD §9)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _api(function: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Return failures as `{"error", "code"?}` instead of raising (API-SPEC preamble)."""

    @functools.wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return function(*args, **kwargs)
        except SpecError as exc:
            return {"error": str(exc), "code": exc.code}
        except (ValueError, RuntimeError, OSError) as exc:
            return {"error": str(exc)}

    return wrapper


def validate_slug(slug: Any) -> str:
    """A spec slug is one FEATURE_NAME_RE segment (BR-14)."""
    if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
        raise SpecError("invalid_spec_slug", f"invalid spec slug: {slug}")
    return slug


def normalize_work_key(work: str) -> str:
    """`x` → `features/x`; `<type>/<name>` stays. `specs/...` is refused (BR-14)."""
    try:
        ensure_safe_name(work)
    except ValueError as exc:
        raise SpecError("reserved_type" if "reserved" in str(exc) else "invalid_work", str(exc)) from None
    return work if "/" in work else f"features/{work}"


def is_archived(meta: dict[str, Any] | None) -> bool:
    return str((meta or {}).get("archived", "")).strip().lower() == "true"


def linked_spec(meta: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """(slug, error) from a PRD/WORK front-matter `spec` field; both None when absent."""
    value = (meta or {}).get("spec")
    if value is None or value == "" or value == {}:
        return None, None
    try:
        return validate_slug(value), None
    except SpecError as exc:
        return None, str(exc)


def primary_doc(item: Path) -> Path | None:
    """WORK.md, else PRD.md, of a work-item directory (no symlinks)."""
    for name in PRIMARY_DOCS:
        path = item / name
        if path.is_file() and not path.is_symlink():
            return path
    return None


def _specs_root(project: Path) -> Path:
    return project.joinpath(*SPECS_DIR)


def _spec_path(project: Path, slug: str) -> Path:
    path = _specs_root(project) / validate_slug(slug) / SPEC_FILE
    safe_path(path, project)
    return path


def write_inside(path: Path, text: str, project: Path, base: Path) -> None:
    """Atomically replace `path` (temp file + rename) after symlink / escape checks.

    `path` and every parent up to `project` must not be a symlink, and `path` must
    resolve inside `base`. An interrupted write leaves the original file untouched.
    """
    safe_path(path, project)
    if not path.resolve().is_relative_to(base.resolve()):
        raise SpecError("path_escape", "write path escapes its directory")
    if path.exists() and not path.is_file():
        raise SpecError("path_escape", f"not a regular file: {path.name}")
    mode = (path.stat().st_mode & 0o777) if path.exists() else 0o644
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary: Path | None = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        safe_path(path, project)  # re-check right before the swap
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Enumeration (front-matter only)
# ---------------------------------------------------------------------------

def _plain_dirs(parent: Path) -> list[Path]:
    if not parent.is_dir() or parent.is_symlink():
        return []
    return sorted(p for p in parent.iterdir() if p.is_dir() and not p.is_symlink() and SLUG_RE.fullmatch(p.name))


def work_items(project: Path) -> list[dict[str, Any]]:
    """Every `docs/<type>/<name>/` holding a WORK.md or PRD.md (`specs` excluded, symlinks skipped).

    Only front-matter is read: `spec`/`archived`/`status` from the primary doc and the
    `status` of each `*.md`.
    """
    docs = project / "docs"
    safe_path(docs, project)
    items = []
    for type_dir in _plain_dirs(docs):
        if type_dir.name in RESERVED_TYPES:
            continue
        for item in _plain_dirs(type_dir):
            primary = primary_doc(item)
            if primary is None:
                continue
            meta = frontmatter.read(primary) or {}
            slug, error = linked_spec(meta)
            statuses = {path.name: (frontmatter.read(path) or {}).get("status")
                        for path in sorted(item.glob("*.md")) if not path.is_symlink()}
            items.append({"key": f"{type_dir.name}/{item.name}", "spec": slug, "spec_error": error,
                          "status": meta.get("status"), "archived": is_archived(meta), "docs": statuses})
    return items


def specs(project: Path) -> list[dict[str, Any]]:
    """`docs/specs/<slug>/SPEC.md` front-matter (symlinks and invalid slugs skipped)."""
    root = _specs_root(project)
    safe_path(root, project)
    found = []
    for directory in _plain_dirs(root):
        path = directory / SPEC_FILE
        if not path.is_file() or path.is_symlink():
            continue
        meta = frontmatter.read(path) or {}
        found.append({"spec": directory.name, "title": meta.get("title") or directory.name,
                      "status": meta.get("status"), "updated": meta.get("updated"), "path": path})
    return found


def _context(root: str | Path | None) -> Path:
    return projects.resolve(root).path


# ---------------------------------------------------------------------------
# spec new / list
# ---------------------------------------------------------------------------

@_api
def spec_new(slug: str, title: str, root: str | None = None) -> dict[str, Any]:
    """Create docs/specs/<slug>/SPEC.md (status: draft) from templates/SPEC.md."""
    validate_slug(slug)
    title = title.strip() if isinstance(title, str) else ""
    if not title or len(title) > 200 or "\n" in title or "\r" in title:
        raise SpecError("invalid_title", "title must be 1-200 characters on one line")
    project = _context(root)
    path = _spec_path(project, slug)
    if path.exists() or path.parent.exists():
        raise SpecError("spec_exists", f"spec already exists: {slug}")
    today = _today()
    raw = (config.TEMPLATES_DIR / SPEC_FILE).read_text(encoding="utf-8")
    text = re.sub(r"^(created|updated):\s*YYYY-MM-DD", rf"\1: {today}", raw, flags=re.M)
    text = frontmatter.update(text.replace("<spec-slug>", slug), {"title": title})
    text = text.replace("# SPEC: <title>", f"# SPEC: {title}", 1)
    path.parent.mkdir(parents=True)
    write_inside(path, text, project, path.parent)
    return {"spec": slug, "path": str(path.relative_to(project)), "status": "created"}


@_api
def spec_list(root: str | None = None) -> dict[str, Any]:
    """Specs with their linked work items, and active work items linked to no spec. No side effects."""
    project = _context(root)
    known = specs(project)
    items = work_items(project)
    slugs = {entry["spec"] for entry in known}
    return {
        "specs": [{"spec": entry["spec"], "title": entry["title"], "status": entry["status"],
                   "updated": entry["updated"],
                   "work_items": [{"key": item["key"], "status": item["status"], "archived": item["archived"]}
                                  for item in items if item["spec"] == entry["spec"]]}
                  for entry in known],
        "unlinked_work_items": [item["key"] for item in items if item["spec"] is None and not item["archived"]],
        "unknown_spec_work_items": [{"key": item["key"], "spec": item["spec"], "error": item["spec_error"]}
                                    for item in items if (item["spec"] and item["spec"] not in slugs)
                                    or item["spec_error"]],
    }


# ---------------------------------------------------------------------------
# spec history-add (BR-4)
# ---------------------------------------------------------------------------

HISTORY_HEADING = re.compile(r"##\s+6\.")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_PR_URL = re.compile(r"https://[^\s|()<>\[\]\\]+")
_PR_NUMBER = re.compile(r"/pull/(\d+)/?$")


def cells(line: str) -> list[str]:
    parts = _CELL_SPLIT.split(line.strip())
    return [part.strip() for part in parts[1:-1]]


def history_table(lines: list[str]) -> tuple[int, list[list[str]]]:
    """(insert index after the last row, data rows) of the section-6 change-history table."""
    fence, heading = None, None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            fence = None if fence == stripped[:3] else stripped[:3] if fence is None else fence
            continue
        if fence:
            continue
        if heading is None:
            heading = index if HISTORY_HEADING.match(stripped) else None
            continue
        if stripped.startswith("#"):
            break
        if stripped.startswith("|"):
            following = lines[index + 1].strip() if index + 1 < len(lines) else ""
            if len(cells(line)) != 4 or not re.fullmatch(r"\|(\s*:?-{3,}:?\s*\|){4}", following):
                break
            end, rows = index + 2, []
            while end < len(lines) and lines[end].strip().startswith("|"):
                rows.append(cells(lines[end]))
                end += 1
            return end, rows
    raise SpecError("history_table_missing", "SPEC change-history table not found")


def _row_key(row: list[str]) -> tuple[str, str]:
    try:
        work = normalize_work_key(row[1])
    except (SpecError, IndexError):
        work = row[1] if len(row) > 1 else ""
    match = _PR_URL.search(row[3]) if len(row) > 3 else None
    return work, match.group(0) if match else ""


def _escape_cell(text: str) -> str:
    return re.sub(r"\s*[\r\n]+\s*", " ", text).replace("|", "\\|").strip()


@_api
def spec_history_add(slug: str, work: str, summary: str, pr: str | None = None,
                     date: str | None = None, root: str | None = None) -> dict[str, Any]:
    """Append `| date | work | summary | [#n](pr) |` to SPEC section 6; same (work, pr) → duplicate."""
    validate_slug(slug)
    key = normalize_work_key(work)
    if not isinstance(summary, str) or not summary.strip() or len(summary.strip()) > 200:
        raise SpecError("invalid_summary", "summary must be 1-200 characters")
    if pr is not None and not _PR_URL.fullmatch(pr):
        raise SpecError("invalid_pr_url", "invalid pr url")
    day = date or _today()
    try:
        date_type.fromisoformat(day if DATE_RE.fullmatch(day) else "invalid")
    except (TypeError, ValueError):
        raise SpecError("invalid_date", "date must be YYYY-MM-DD") from None
    project = _context(root)
    path = _spec_path(project, slug)
    if not path.is_file():
        raise SpecError("spec_not_found", f"spec not found: {slug}")
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    end, rows = history_table(lines)
    if (key, pr or "") in {_row_key(row) for row in rows}:
        return {"spec": slug, "path": str(path.relative_to(project)), "status": "duplicate"}
    number = _PR_NUMBER.search(pr) if pr else None
    link = f"[#{number.group(1)}]({pr})" if number else f"[PR]({pr})" if pr else "-"
    row = f"| {day} | {key} | {_escape_cell(summary)} | {link} |"
    lines.insert(end, row)
    write_inside(path, frontmatter.update("\n".join(lines), {"updated": _today()}), project, path.parent)
    return {"spec": slug, "path": str(path.relative_to(project)), "status": "added", "row": row}


def _today() -> str:
    return date_type.today().isoformat()


# ---------------------------------------------------------------------------
# feature-archive (Q-1)
# ---------------------------------------------------------------------------

def _finished(item: Path, key: str) -> bool:
    """cicd outputs of the item's track all exist and are approved (BR-15)."""
    track = "work" if (item / "WORK.md").is_file() else "light" if key.startswith(LIGHT_TRACK_PREFIXES) else "full"
    for name in AGENT_OUTPUTS_BY_TRACK[track]["cicd"]:
        path = item / name
        if path.is_symlink() or (frontmatter.read(path) or {}).get("status") != "approved":
            return False
    return True


@_api
def feature_archive(feature: str, undo: bool = False, force: bool = False,
                    root: str | None = None) -> dict[str, Any]:
    """Set (or with undo remove) `archived: true` in every *.md front-matter of a work item.

    `updated` is kept so approvals stay valid. Unfinished items (cicd outputs not
    approved) need `force`.
    """
    key = normalize_work_key(feature)
    project = _context(root)
    item = config.docs_dir(key, project_dir=project)
    safe_path(item, project)
    if not item.is_dir():
        raise SpecError("feature_not_found", f"Feature not found: {key}")
    if not undo and not force and not _finished(item, key):
        raise SpecError("archive_in_progress", "work item is not finished; pass --force")
    changed, unchanged, skipped = [], [], []
    for path in sorted(item.glob("*.md")):
        safe_path(path, project)
        text = path.read_text(encoding="utf-8")
        if frontmatter.parse(text) is None:
            skipped.append(path.name)
            continue
        new = frontmatter.update(text, {"archived": None if undo else "true"})
        if new == text:
            unchanged.append(path.name)
            continue
        write_inside(path, new, project, item)
        changed.append(path.name)
    return {"feature": key, "archived": not undo, "files": changed + unchanged, "changed": changed,
            "skipped_no_frontmatter": skipped}


# ---------------------------------------------------------------------------
# CLI (kept here so cli.py only delegates)
# ---------------------------------------------------------------------------

MCP_TOOLS = (spec_new, spec_list, spec_history_add, feature_archive)


def register_mcp(mcp: Any) -> None:
    """Register the spec tools on the FastMCP server (server.py only delegates)."""
    for tool in MCP_TOOLS:
        mcp.tool()(tool)


def add_cli(subparsers: Any) -> None:
    spec_parser = subparsers.add_parser("spec", help="Feature specs: docs/specs/<slug>/SPEC.md")
    actions = spec_parser.add_subparsers(dest="spec_action", required=True)
    created = actions.add_parser("new", help="Create a SPEC skeleton (status: draft)")
    created.add_argument("slug")
    created.add_argument("--title", required=True)
    actions.add_parser("list", help="Specs, linked work items and unlinked work items")
    history = actions.add_parser("history-add", help="Append a change-history row (idempotent)")
    history.add_argument("slug")
    history.add_argument("--work", required=True)
    history.add_argument("--summary", required=True)
    history.add_argument("--pr")
    history.add_argument("--date")
    for command in (created, actions.choices["list"], history):
        command.add_argument("--root")
    archive = subparsers.add_parser("feature-archive", help="Mark a finished work item archived (front-matter only)")
    archive.add_argument("feature")
    archive.add_argument("--undo", action="store_true")
    archive.add_argument("--force", action="store_true", help="Archive even when cicd outputs are not approved")
    archive.add_argument("--root")
    spec_set = subparsers.add_parser(
        "project-spec-set", help="User only: require a spec link before the backend handoff (writes the registry)")
    spec_set.add_argument("project_id")
    spec_set.add_argument("--required", required=True, choices=["true", "false"])


def run_cli(args: argparse.Namespace, emit: Callable[[dict[str, Any]], None]) -> int | None:
    """Run a command added by `add_cli`; None when `args.command` is not one of them."""
    if args.command == "project-spec-set":
        emit(projects.set_spec_required(args.project_id, args.required == "true"))
        return 0
    if args.command == "feature-archive":
        result = feature_archive(args.feature, undo=args.undo, force=args.force, root=args.root)
    elif args.command == "spec":
        action = args.spec_action
        result = (spec_new(args.slug, args.title, root=args.root) if action == "new"
                  else spec_list(root=args.root) if action == "list"
                  else spec_history_add(args.slug, args.work, args.summary, pr=args.pr, date=args.date,
                                        root=args.root))
    else:
        return None
    emit(result)
    return 1 if "error" in result else 0
