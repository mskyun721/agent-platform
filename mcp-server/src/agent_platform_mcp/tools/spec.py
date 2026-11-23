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
import contextlib
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

try:
    import fcntl
except ImportError:  # non-POSIX: history-add runs without the directory lock
    fcntl = None

SLUG_RE = re.compile(NAME_SEGMENT)
SPECS_DIR = ("docs", "specs")
SPEC_FILE = "SPEC.md"
PRIMARY_DOCS = ("WORK.md", "PRD.md")  # where a work item's `spec` / `archived` is read
# Work-item folders `feature-archive` may change: the branch types of standards/commit-convention.md
# (feat → features) plus `research` (investment roles). `specs`, `experience`, `db`... are refused.
WORK_TYPES = ("features", "fix", "hotfix", "refactor", "research")


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


def read_raw(path: Path) -> str:
    """UTF-8 text with line endings kept as they are (`read_text` would turn CRLF into LF)."""
    return path.read_bytes().decode("utf-8")


@contextlib.contextmanager
def _directory_lock(directory: Path):
    """Exclusive flock on the directory itself (a stable inode; atomic file swaps change the file's)."""
    if fcntl is None:
        yield
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)  # closing releases the lock


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
    try:
        text = frontmatter.update(text.replace("<spec-slug>", slug), {"title": title})
    except ValueError as exc:  # e.g. a quoted title does not read back unchanged
        raise SpecError("invalid_title", f"title cannot be stored in front-matter: {exc}") from None
    text = text.replace("# SPEC: <title>", f"# SPEC: {_escape_cell(title)}", 1)
    path.parent.mkdir(parents=True)
    try:
        write_inside(path, text, project, path.parent)
    except (OSError, ValueError) as exc:
        with contextlib.suppress(OSError):
            path.parent.rmdir()  # no empty directory, so a retry is not `spec_exists`
        raise SpecError(getattr(exc, "code", "write_failed"), str(exc)) from None
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
# A `|` ends a cell unless an odd number of backslashes precede it (`\\|` is a backslash, then a column).
_CELL_SPLIT = re.compile(r"(?<!\\)((?:\\\\)*)\|")
_PR_URL = re.compile(r"https://[^\s|()<>\[\]\\]+")
_PR_NUMBER = re.compile(r"/pull/(\d+)$")
# Backslash first, then table and inline-markup characters: no HTML, image or link survives (Security L-1).
_MARKUP = re.compile(r"([\\|<>!\[\]])")


def cells(line: str) -> list[str]:
    parts = _CELL_SPLIT.sub(lambda match: match.group(1) + "\0", line.strip()).split("\0")
    return [part.strip() for part in parts[1:-1]]


def normalize_pr(url: str) -> str:
    """Compare PR URLs without `#fragment`, `?query` or a trailing `/` (Review L-3)."""
    return url.split("#", 1)[0].split("?", 1)[0].rstrip("/")


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
    return work, normalize_pr(match.group(0)) if match else ""


def _escape_cell(text: str) -> str:
    """One line, with `\\`, `|`, `<`, `>`, `!`, `[`, `]` backslash-escaped (a trailing `\\` stays literal)."""
    return _MARKUP.sub(r"\\\1", re.sub(r"\s*[\r\n]+\s*", " ", text).strip())


@_api
def spec_history_add(slug: str, work: str, summary: str, pr: str | None = None,
                     date: str | None = None, root: str | None = None) -> dict[str, Any]:
    """Append `| date | work | summary | [#n](pr) |` to SPEC section 6; same (work, pr) → duplicate."""
    validate_slug(slug)
    key = normalize_work_key(work)
    if not isinstance(summary, str) or not summary.strip() or len(summary.strip()) > 200:
        raise SpecError("invalid_summary", "summary must be 1-200 characters")
    if pr is not None and not (isinstance(pr, str) and _PR_URL.fullmatch(pr) and _PR_URL.fullmatch(normalize_pr(pr))):
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
    pr = normalize_pr(pr) if pr else None
    with _directory_lock(path.parent):  # concurrent adds must not drop a row (Review L-7)
        text = read_raw(path)
        lines = text.split("\n")
        end, rows = history_table(lines)
        if (key, pr or "") in {_row_key(row) for row in rows}:
            return {"spec": slug, "path": str(path.relative_to(project)), "status": "duplicate"}
        number = _PR_NUMBER.search(pr) if pr else None
        link = f"[#{number.group(1)}]({pr})" if number else f"[PR]({pr})" if pr else "-"
        row = f"| {day} | {key} | {_escape_cell(summary)} | {link} |"
        lines.insert(end, row + ("\r" if "\r\n" in text else ""))
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
    approved) need `force`. Every file is checked and its new text built before the first
    write; a failed check writes nothing (`archive_invalid`, `file`). A failed write rolls
    back the files already written (`archive_write_failed`, `rolled_back`, `changed`).
    """
    key = normalize_work_key(feature)
    if key.split("/", 1)[0] not in WORK_TYPES:
        raise SpecError("invalid_work_type", f"not a work-item type: {key.split('/', 1)[0]} "
                                             f"(allowed: {', '.join(WORK_TYPES)})")
    project = _context(root)
    item = config.docs_dir(key, project_dir=project)
    safe_path(item, project)
    if not item.is_dir():
        raise SpecError("feature_not_found", f"Feature not found: {key}")
    if not undo and not force and not _finished(item, key):
        raise SpecError("archive_in_progress", "work item is not finished; pass --force")
    planned, unchanged, skipped = [], [], []
    for path in sorted(item.glob("*.md")):
        try:
            safe_path(path, project)
            text = read_raw(path)
            new = frontmatter.update(text, {"archived": None if undo else "true"}) \
                if frontmatter.parse(text) is not None else None
        except (ValueError, OSError) as exc:
            return {"error": f"{path.name}: {exc}; no file was changed", "code": "archive_invalid",
                    "file": path.name, "changed": []}
        if new is None:
            skipped.append(path.name)
        elif new == text:
            unchanged.append(path.name)
        else:
            planned.append((path, text, new))
    written: list[tuple[Path, str]] = []
    for path, text, new in planned:
        try:
            write_inside(path, new, project, item)
        except (ValueError, OSError) as exc:
            return _archive_rollback(key, path.name, exc, written, project, item)
        written.append((path, text))
    changed = [path.name for path, _text, _new in planned]
    return {"feature": key, "archived": not undo, "files": changed + unchanged, "changed": changed,
            "skipped_no_frontmatter": skipped}


def _archive_rollback(key: str, failed: str, exc: Exception, written: list[tuple[Path, str]],
                      project: Path, item: Path) -> dict[str, Any]:
    """Restore the original text of files already written; report the ones that could not be restored."""
    rolled_back, still_changed = [], []
    for path, original in reversed(written):
        try:
            write_inside(path, original, project, item)
            rolled_back.append(path.name)
        except (ValueError, OSError):
            still_changed.append(path.name)
    return {"error": f"writing {failed} failed: {exc}", "code": "archive_write_failed", "feature": key,
            "file": failed, "rolled_back": sorted(rolled_back), "changed": sorted(still_changed)}


# ---------------------------------------------------------------------------
# spec index (BR-5) and the gate report (BR-3)
# ---------------------------------------------------------------------------

INDEX_FILE = "INDEX.md"
INDEX_MARK = "<!-- generated by spec index; do not edit -->"
HIDDEN_WORK = "(비공개)"


def _cell(text: Any) -> str:
    return _escape_cell(str(text)) if text not in (None, "") else "-"


def _doc_states(item: dict[str, Any]) -> str:
    return ", ".join(f"{Path(name).stem}: {status or '-'}" for name, status in item["docs"].items())


_DEFECT_KEY = re.compile(r"(?<![a-z0-9-])(?:hot)?fix/")


def is_defect_work(cell: str) -> bool:
    """Remote mode hides this work cell: a fix/ or hotfix/ key in any case or markup, or no plain work key.

    A cell that is not a valid work key (hand-edited `[fix/x](..)`, `` `Fix/x` ``...) is hidden too,
    so hiding never depends on the exact raw text (Security L-4).
    """
    if _DEFECT_KEY.search(cell.lower()):
        return True
    try:
        normalize_work_key(cell.strip())
    except SpecError:
        return True
    return False


# The PR cell history-add writes: `[#n](https://...)` or `[PR](https://...)`.
_PR_LINK = re.compile(r"\[(?:#\d+|PR)\]\(https://[^\s|()<>\[\]\\]+\)")


_PR_LABEL = re.compile(r"\[#(\d+)\]")
_URL_NUMBER = re.compile(r"/(\d+)\)$")


def _remote_safe(day: str, pr: str) -> tuple[str, str]:
    """Remote pages: a hand-edited date or PR cell that history-add would not write is dropped (N-1),
    so no HTML, image or other link reaches the published page. A kept PR link is reduced to `#n`
    (or `PR`) without the repository URL (Security 4b L-2)."""
    if not _PR_LINK.fullmatch(pr):
        return (day if DATE_RE.fullmatch(day) else "-"), "-"
    number = _PR_LABEL.match(pr) or _URL_NUMBER.search(pr)
    return (day if DATE_RE.fullmatch(day) else "-"), f"#{number.group(1)}" if number else "PR"


def _remote_row(row: list[str]) -> str:
    if len(row) != 4:  # a row history-add did not write: nothing in it is trusted
        return f"| - | {HIDDEN_WORK} | - | - |"
    day, key, summary, pr = row
    day, pr = _remote_safe(day, pr)
    if is_defect_work(key):  # the same rule as the remote INDEX (BR-5, Review 4b M-1)
        return f"| {day} | {HIDDEN_WORK} | - | - |"
    return f"| {day} | {key} | {summary or '-'} | {pr} |"


def remote_history(text: str) -> str:
    """SPEC text for a published page: §6 rows of fix/·hotfix/ work become `date | (비공개)` with no
    summary or PR, the others keep a `#n` PR cell only. A §6 heading whose table cannot be read
    raises SpecError(`history_unparsed`) so an unreadable history is never sent as is."""
    lines = text.split("\n")
    try:
        end, rows = history_table(lines)
    except SpecError:
        if any(HISTORY_HEADING.match(line.strip()) for line in lines):
            raise SpecError("history_unparsed", "SPEC change-history table could not be read") from None
        return text
    for index, row in enumerate(rows, end - len(rows)):
        lines[index] = _remote_row(row)
    return "\n".join(lines)


def _last_change(path: Path, hide: Callable[[str], bool], remote: bool = False) -> str:
    try:
        rows = history_table(read_raw(path).split("\n"))[1]
    except (SpecError, OSError, UnicodeDecodeError):
        return "-"
    if not rows or len(rows[-1]) != 4:
        return "-"
    day, key, _summary, pr = rows[-1]
    if remote:
        day, pr = _remote_safe(day, pr)
    if hide(key):  # no PR link or repository URL for a hidden defect row (Security M-1)
        return " · ".join(part for part in (day, HIDDEN_WORK) if part and part != "-")
    return " · ".join(part for part in (day, key, pr) if part and part != "-")


def index_markdown(project: Path, remote: bool = False) -> tuple[str, dict[str, int]]:
    """INDEX.md text from front-matter and the last §6 row of each SPEC (no AI, no timestamps).

    The git copy has no machine-specific values (no published-page links). `remote=True` is
    for a published INDEX page: only approved SPECs are listed (Security 4b L-3), fix/ and hotfix/
    work names are left out (BR-5, L-5), PR cells are `#n` only and spec titles are not linked to
    repository paths.
    """
    hide = is_defect_work if remote else (lambda key: False)
    known, items = specs(project), work_items(project)
    slugs = {entry["spec"] for entry in known}
    # Remote: only approved SPECs are listed; work of the others is left out too (Security 4b L-3).
    pending = {entry["spec"] for entry in known if remote and entry["status"] != "approved"}
    known = [entry for entry in known if entry["spec"] not in pending]
    items = [item for item in items if item["spec"] not in pending]
    active = [item for item in items if not item["archived"]]
    lines = [INDEX_MARK, "# 기능 목록", "", "| 기능 | 상태 | 최근 변경 | 진행 중 작업 |", "|---|---|---|---|"]
    hidden = 0
    for entry in known:
        linked = [item for item in active if item["spec"] == entry["spec"]]
        shown = [item for item in linked if not hide(item["key"])]
        hidden += len(linked) - len(shown)
        title = _cell(entry["title"])
        if not remote:
            title = f"[{title}]({entry['spec']}/{SPEC_FILE})"  # `_cell` already escaped `[`, `]` and `\\`
        progress = "; ".join(f"{item['key']} ({_doc_states(item)})" for item in shown) or "-"
        lines.append(f"| {title} | {_cell(entry['status'])} | {_last_change(entry['path'], hide, remote)} | {_cell(progress)} |")
    unlinked = [item for item in active if item["spec"] not in slugs]
    lines += ["", "## 연결 안 된 작업", "", "| 작업 | spec 값 | 문서 상태 |", "|---|---|---|"]
    for item in unlinked:
        if hide(item["key"]):
            hidden += 1
            continue
        value = item["spec"] or ("(잘못된 값)" if item["spec_error"] else "-")
        lines.append(f"| {item['key']} | {_cell(value)} | {_cell(_doc_states(item))} |")
    archived = [item for item in items if item["archived"]]
    lines += ["", "## 보관", "", "| 작업 | 기능 |", "|---|---|"]
    for item in archived:
        if hide(item["key"]):
            hidden += 1
            continue
        lines.append(f"| {item['key']} | {_cell(item['spec'])} |")
    if hidden:
        lines += ["", f"> 비공개 결함 작업(fix/·hotfix/) {hidden}건은 표시하지 않는다."]
    if pending:
        lines += ["", f"> 승인 전 SPEC {len(pending)}건과 그 작업은 표시하지 않는다."]
    return "\n".join(lines) + "\n", {"specs": len(known), "work_items": len(items), "archived": len(archived)}


@_api
def spec_index(root: str | None = None) -> dict[str, Any]:
    """Rewrite docs/specs/INDEX.md (git copy: no published links, no timestamps)."""
    project = _context(root)
    directory = _specs_root(project)
    safe_path(directory / INDEX_FILE, project)
    text, counts = index_markdown(project)
    directory.mkdir(parents=True, exist_ok=True)
    write_inside(directory / INDEX_FILE, text, project, directory)
    return {"path": "/".join((*SPECS_DIR, INDEX_FILE)), **counts}


def gate_report(context: Any, item: Path, track: str) -> dict[str, Any]:
    """Gate `spec` key: ok | missing | unknown_spec | not_applicable (report only by default).

    `blocks_backend` is true only when the project's registry record sets `spec_required`.
    With `spec_required` a missing link is `missing` whether or not `docs/specs/` exists;
    without it, a project with no `docs/specs/` is `not_applicable` (API-SPEC §8).
    """
    project = context.path
    required = projects.spec_required(context.project_id)
    report: dict[str, Any] = {"status": "not_applicable", "spec": None, "required": required}
    if project == config.ROOT.resolve():
        report["blocks_backend"] = False
        return report
    primary = item / ("WORK.md" if track == "work" else "PRD.md")
    meta = None if primary.is_symlink() else frontmatter.read(primary)
    slug, error = linked_spec(meta)
    if error:
        report.update(status="unknown_spec", reason=error)
    elif slug is None:  # required: missing even before docs/specs/ exists (Review M-2, option b)
        report["status"] = "missing" if required or _specs_root(project).is_dir() else "not_applicable"
    else:
        path = _specs_root(project) / slug / SPEC_FILE
        found = path.is_file() and not any(node.is_symlink() for node in (path, path.parent, path.parent.parent))
        report.update(spec=slug, status="ok" if found else "unknown_spec")
    report["blocks_backend"] = required and report["status"] in {"missing", "unknown_spec"}
    return report


# ---------------------------------------------------------------------------
# spec bootstrap (BR-9): read-only source bundles for the planner
# ---------------------------------------------------------------------------

_METHOD = r"(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)"
_INLINE_OP = re.compile(rf"\b{_METHOD}\s+`?(/[A-Za-z0-9_{{}}./:@-]*)")
_TABLE_METHOD = re.compile(rf"\|\s*Method\s*\|\s*`?{_METHOD}`?\s*\|")
_TABLE_PATH = re.compile(r"\|\s*Path\s*\|\s*`?(/[^`|\s]*)`?\s*\|")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
WALK_SKIP = {".git", ".gradle", ".idea", ".local", ".venv", "__pycache__", "build", "dist", "docs",
             "graphify-out", "node_modules", "out", "target"}


def _operations(path: Path, project: Path) -> list[dict[str, str]]:
    """(method, path) pairs from an API-SPEC: `POST /v1/x` text and `| Method |`/`| Path |` table rows."""
    if not path.is_file() or path.is_symlink():
        return []
    found, method = set(), None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if match := _TABLE_METHOD.match(stripped):
            method = match.group(1)
            continue
        if method and (match := _TABLE_PATH.match(stripped)):
            found.add((method, match.group(1)))
            method = None
            continue
        found.update((m.group(1), m.group(2).rstrip(".,:")) for m in _INLINE_OP.finditer(line))
    source = str(path.relative_to(project))
    return [{"method": m, "path": p, "source": source} for m, p in sorted(found) if p != "/"]


def _migrations(project: Path) -> list[str]:
    """Files under any `db/migration/` directory (build, VCS and docs trees skipped, no symlinks)."""
    found = []
    for directory, subdirs, files in os.walk(project, followlinks=False):
        subdirs[:] = sorted(d for d in subdirs if d not in WALK_SKIP and not d.startswith("."))
        parts = Path(directory).relative_to(project).parts
        if any(parts[i:i + 2] == ("db", "migration") for i in range(len(parts))):
            found += [str(Path(directory, name).relative_to(project)) for name in sorted(files)
                      if not Path(directory, name).is_symlink()]
    return sorted(found)


def _tables(project: Path) -> list[str]:
    """Table names (first cell) of `docs/db/DB-CATALOG.md` section 2."""
    path = project / "docs" / "db" / "DB-CATALOG.md"
    safe_path(path, project)
    if not path.is_file():
        return []
    tables, inside = [], False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("## "):
            inside = bool(re.match(r"##\s+2\.", line))
            continue
        row = cells(line) if inside and line.strip().startswith("|") else []
        name = row[0].strip("`") if row else ""
        if _IDENTIFIER.fullmatch(name) and name not in tables:
            tables.append(name)
    return tables


def _slugify(text: str) -> str | None:
    slug = re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")[:64].rstrip("-")
    return slug if SLUG_RE.fullmatch(slug) else None


def _first_segment(path: str) -> str | None:
    for segment in path.split("/"):
        if segment and segment != "api" and not re.fullmatch(r"v\d+", segment) and segment[0] not in "{:":
            return _slugify(segment)
    return None


def _owner(name: str, slugs: list[str]) -> str | None:
    """The longest candidate slug whose words appear in a table / migration name."""
    lowered = name.lower().replace("_", "-")
    hits = [slug for slug in slugs if slug in lowered or slug.removesuffix("s") in lowered]
    return max(hits, key=len) if hits else None


@_api
def spec_bootstrap(root: str | None = None) -> dict[str, Any]:
    """Group existing approved work docs, API operations, migrations and DB-CATALOG tables by
    feature candidate. Read-only; paths and identifiers only, never document bodies."""
    project = _context(root)
    candidates: dict[str, dict[str, Any]] = {}
    unassigned: dict[str, list[Any]] = {"work_items": [], "migrations": [], "tables": []}
    for item in work_items(project):
        if item["archived"]:
            continue
        approved = [f"docs/{item['key']}/{name}" for name, status in item["docs"].items() if status == "approved"]
        if not approved:
            unassigned["work_items"].append(item["key"])
            continue
        operations = (_operations(project / "docs" / item["key"] / "API-SPEC.md", project)
                      if item["docs"].get("API-SPEC.md") == "approved" else [])  # BR-9, Review L-6
        segments = [s for s in (_first_segment(op["path"]) for op in operations) if s]
        slug = item["spec"] or (max(sorted(set(segments)), key=segments.count) if segments else None) \
            or _slugify(item["key"].split("/")[-1])
        entry = candidates.setdefault(slug, {"suggested_slug": slug, "existing_spec": (
            _specs_root(project) / slug / SPEC_FILE).is_file(), "work_items": [], "operations": [],
            "migrations": [], "tables": []})
        entry["work_items"].append({"key": item["key"], "docs": approved})
        entry["operations"] += [op for op in operations if op not in entry["operations"]]
    slugs = sorted(candidates)
    for kind, names in (("migrations", _migrations(project)), ("tables", _tables(project))):
        for name in names:
            owner = _owner(Path(name).name, slugs)
            (candidates[owner][kind] if owner else unassigned[kind]).append(name)
    return {"candidates": [candidates[slug] for slug in slugs], "unassigned": unassigned,
            "note": "draft grouping by API path and work name; the planner adjusts it and writes SPEC drafts"}


# ---------------------------------------------------------------------------
# CLI (kept here so cli.py only delegates)
# ---------------------------------------------------------------------------

MCP_TOOLS = (spec_new, spec_list, spec_index, spec_history_add, spec_bootstrap, feature_archive)


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
    actions.add_parser("index", help="Rewrite docs/specs/INDEX.md from front-matter")
    actions.add_parser("bootstrap", help="Read-only source bundles per feature candidate (JSON)")
    history = actions.add_parser("history-add", help="Append a change-history row (idempotent)")
    history.add_argument("slug")
    history.add_argument("--work", required=True)
    history.add_argument("--summary", required=True)
    history.add_argument("--pr")
    history.add_argument("--date")
    for command in (created, history, *(actions.choices[name] for name in ("list", "index", "bootstrap"))):
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
                  else spec_index(root=args.root) if action == "index"
                  else spec_bootstrap(root=args.root) if action == "bootstrap"
                  else spec_history_add(args.slug, args.work, args.summary, pr=args.pr, date=args.date,
                                        root=args.root))
    else:
        return None
    emit(result)
    return 1 if "error" in result else 0
