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
from pathlib import Path
from typing import Any, Callable

from agent_platform_mcp import frontmatter
from agent_platform_mcp.tools import projects
from agent_platform_mcp.tools.feature import NAME_SEGMENT, ensure_safe_name, safe_path

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
# CLI (kept here so cli.py only delegates)
# ---------------------------------------------------------------------------

def add_cli(subparsers: Any) -> None:
    spec_set = subparsers.add_parser(
        "project-spec-set", help="User only: require a spec link before the backend handoff (writes the registry)")
    spec_set.add_argument("project_id")
    spec_set.add_argument("--required", required=True, choices=["true", "false"])


def run_cli(args: argparse.Namespace, emit: Callable[[dict[str, Any]], None]) -> int | None:
    """Run a command added by `add_cli`; None when `args.command` is not one of them."""
    if args.command == "project-spec-set":
        emit(projects.set_spec_required(args.project_id, args.required == "true"))
        return 0
    return None
