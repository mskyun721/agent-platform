"""Local project identity registry with atomic updates and explicit rebinding."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_platform_mcp import config

try:
    import fcntl
except ImportError:  # Read-only resolution remains available outside POSIX.
    fcntl = None

REGISTRY_FILE = config.ROOT / ".agent-projects.json"
ID_RE = re.compile(r"[a-z][a-z0-9-]{1,63}")


@dataclass(frozen=True)
class ProjectContext:
    project_id: str | None
    path: Path
    verify_profile_id: str | None = None


def _safe_storage(path: Path) -> None:
    if any(node.is_symlink() for node in (path, *path.parents)):
        raise ValueError("project registry storage cannot use symlinks")


safe_storage = _safe_storage


def _read() -> dict[str, Any]:
    _safe_storage(REGISTRY_FILE)
    if not REGISTRY_FILE.exists():
        return {"schema": 1, "projects": {}}
    data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 1 or not isinstance(data.get("projects"), dict):
        raise ValueError("unsupported project registry schema")
    for key, record in data["projects"].items():
        if not ID_RE.fullmatch(key) or not isinstance(record, dict):
            raise ValueError("invalid project registry record")
        if not isinstance(record.get("path"), str) or not Path(record["path"]).is_absolute():
            raise ValueError("registered project path must be absolute")
        for field in ("git_common_dir", "verify_profile_id"):
            if record.get(field) is not None and not isinstance(record[field], str):
                raise ValueError(f"invalid project registry {field}")
    return data


@contextmanager
def _locked():
    if fcntl is None:
        raise RuntimeError("project registry writes require POSIX file locking")
    lock = REGISTRY_FILE.with_suffix(".lock")
    _safe_storage(lock)
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("project registry is busy")
                time.sleep(0.05)
        yield
    finally:
        os.close(descriptor)


def _write(data: dict[str, Any]) -> None:
    _safe_storage(REGISTRY_FILE)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=REGISTRY_FILE.parent,
                                         prefix=".agent-projects.json.", delete=False) as output:
            temporary = Path(output.name)
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, REGISTRY_FILE)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _common_dir(path: Path) -> str | None:
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=path,
                             capture_output=True, text=True, timeout=10, check=False)
        if top.returncode or Path(top.stdout.strip()).resolve() != path:
            return None
        proc = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=path,
                              capture_output=True, text=True, timeout=10, check=False)
        if proc.returncode:
            return None
        return str((path / proc.stdout.strip()).resolve())
    except (OSError, subprocess.TimeoutExpired):
        return None


def register(path: str, project_id: str | None = None, verify_profile: str | None = None) -> dict[str, Any]:
    target = config._resolve_project_path(path)
    project_id = project_id if project_id is not None else f"project-{uuid.uuid4().hex}"
    if not ID_RE.fullmatch(project_id):
        raise ValueError("project_id must be 2-64 lowercase letters, digits or dashes")
    if verify_profile is not None and verify_profile not in config.agent_config().get("verify_profiles", {}):
        raise ValueError("unknown verify profile")
    common = _common_dir(target)
    record = {"path": str(target), "git_common_dir": common, "verify_profile_id": verify_profile,
              "registered_at": datetime.now(timezone.utc).isoformat()}
    with _locked():
        data = _read()
        if project_id in data["projects"]:
            raise ValueError("project_id already registered")
        for existing in data["projects"].values():
            if existing["path"] == str(target) or (common and existing.get("git_common_dir") == common):
                raise ValueError("project or worktree already registered; use its existing identity")
        data["projects"][project_id] = record
        _write(data)
    return {"project_id": project_id, **record}


def _active_path() -> str | None:
    try:
        active = config.target_project_root()
    except RuntimeError:  # stale .active-project outside the allowlist
        return None
    return str(active) if active else None


def list_projects() -> dict[str, Any]:
    records = _read()["projects"]
    active = _active_path()
    by_path = {value["path"]: key for key, value in records.items()}
    targets = [{"name": path.name, "path": str(path), "default": str(path) == active,
                "project_id": by_path.get(str(path)), "exists": path.is_dir()}
               for path in config.active_projects()]
    return {"schema": 1, "active_path": active, "active_targets": targets,
            "projects": [{"project_id": key, **value, "publish": value.get("publish"), "active": value["path"] == active}
                         for key, value in sorted(records.items())]}


def use(ref: str) -> dict[str, Any]:
    """Make a project the default target: first line of .active-project.

    `ref` is a registered project_id, the folder name of a listed target, or a path.
    Other listed targets are kept.
    """
    context = resolve(ref)
    config.set_active_project(context.path)  # enforces the allowlist
    return {"project_id": context.project_id, "path": str(context.path), "active": True,
            "active_targets": [str(path) for path in config.active_projects()]}


_GIT_URL = re.compile(r"(https://|ssh://|file://|git@[\w.-]+:)[\w./~:@%+-]+")


def _is_git_url(ref: str) -> bool:
    return bool(_GIT_URL.fullmatch(ref))


def _clone(url: str, into: str | None) -> Path:
    """Clone `url` into an allowed root and return the checkout; reuse an existing clone."""
    parent = Path(into).expanduser().resolve() if into else config.allowed_project_roots()[0]
    name = url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1].removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ValueError("cannot derive a folder name from the repository URL")
    destination = config._ensure_within_allowed_roots(parent / name)
    if destination.exists():
        origin = subprocess.run(["git", "-C", str(destination), "remote", "get-url", "origin"],
                                capture_output=True, text=True, timeout=10, check=False)
        if origin.returncode or origin.stdout.strip() != url:
            raise FileExistsError(f"{destination} exists and is not a clone of this repository")
        return destination
    parent.mkdir(parents=True, exist_ok=True)
    # argv only, `--` ends options, and no credential prompt can block a tool call.
    result = subprocess.run(["git", "clone", "--", url, str(destination)], capture_output=True, text=True,
                            timeout=600, check=False, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if result.returncode:
        raise RuntimeError(f"git clone failed: {result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'unknown error'}")
    return destination


def add(ref: str, into: str | None = None, default: bool = False) -> dict[str, Any]:
    """Add a target to .active-project from a local path or a git repository URL.

    A URL is cloned into `into` (default: the first allowed root) first — roles always
    work on a local checkout. The default target changes only with `default` or when
    the list was empty. CLI-only on purpose: agents must not clone arbitrary remotes.
    """
    cloned = _is_git_url(ref)
    path = _clone(ref, into) if cloned else config._resolve_project_path(ref)
    if path == config.ROOT.resolve():
        raise ValueError("the platform itself is selected with --root, not listed as a target")
    if default or not config.active_projects():
        config.set_active_project(path)
    else:
        config.add_active_project(path)
    return {"path": str(path), "cloned_from": ref if cloned else None,
            "default": config.active_projects()[0] == path,
            "active_targets": [str(entry) for entry in config.active_projects()]}


def rebind(project_id: str, new_path: str) -> dict[str, Any]:
    target = config._resolve_project_path(new_path)
    common = _common_dir(target)
    with _locked():
        data = _read()
        if project_id not in data["projects"]:
            raise ValueError("unknown project_id")
        for key, record in data["projects"].items():
            if key != project_id and (record["path"] == str(target) or (common and record.get("git_common_dir") == common)):
                raise ValueError("destination belongs to another project")
        record = data["projects"][project_id]
        if record.get("skills") and record["path"] != str(target):
            raise RuntimeError("disable managed skills before rebinding the project")
        record.update(path=str(target), git_common_dir=common, rebound_at=datetime.now(timezone.utc).isoformat())
        _write(data)
    return {"project_id": project_id, **record}


def unregister(project_id: str) -> dict[str, Any]:
    with _locked():
        data = _read()
        if project_id not in data["projects"]:
            raise ValueError("unknown project_id")
        if data["projects"][project_id].get("skills"):
            raise RuntimeError("disable managed skills before unregistering the project")
        del data["projects"][project_id]
        _write(data)
    return {"project_id": project_id, "removed": True}


PUBLISH_TARGETS = ("none", "confluence", "notion")
_NOTION_ID_RE = re.compile(r"[0-9a-fA-F]{32}")


class InvalidSettings(ValueError):
    """A stored `publish` record is unusable; the message names the field, never its value."""


def normalize_notion_id(value: Any) -> str | None:
    """32 hex chars (hyphens allowed) → lowercase without hyphens; anything else → None."""
    if not isinstance(value, str):
        return None
    compact = value.strip().replace("-", "")
    return compact.lower() if _NOTION_ID_RE.fullmatch(compact) else None


def _check_publish(publish: Any) -> dict[str, Any]:
    """Validate one `publish` record; raises InvalidSettings naming the bad field."""
    if not isinstance(publish, dict):
        raise InvalidSettings("Invalid publish settings: publish")
    target = publish.get("target")
    if target not in PUBLISH_TARGETS:
        raise InvalidSettings("Invalid publish settings: target")
    if target == "notion":
        notion = publish.get("notion")
        if not isinstance(notion, dict) or normalize_notion_id(notion.get("parent_page_id")) is None:
            raise InvalidSettings("Invalid publish settings: notion.parent_page_id")
    if target == "confluence":
        confluence = publish.get("confluence")
        if not isinstance(confluence, dict):
            raise InvalidSettings("Invalid publish settings: confluence")
        for key in ("space_key", "parent_title"):
            if not isinstance(confluence.get(key), str) or not confluence[key].strip():
                raise InvalidSettings(f"Invalid publish settings: confluence.{key}")
    return publish


def get_publish(project_id: str | None) -> dict[str, Any] | None:
    """Stored publish settings for a project, or None when unregistered / unset.

    Validation is done here rather than in `_read()` so a damaged `publish` field only
    breaks publishing, never scaffold/gate/handoff resolution of the same project.
    """
    if project_id is None:
        return None
    record = _read()["projects"].get(project_id)
    if record is None or record.get("publish") is None:
        return None
    return _check_publish(record["publish"])


def set_publish(project_id: str, target: str, notion_parent_page_id: str | None = None,
                confluence_space_key: str | None = None,
                confluence_parent_title: str | None = None) -> dict[str, Any]:
    """Store a project's publish target (IDs only, never secrets). Same input → same record."""
    if target not in PUBLISH_TARGETS:
        raise ValueError("target must be one of: none, confluence, notion")
    publish: dict[str, Any] = {"target": target}
    if target == "notion":
        if not notion_parent_page_id:
            raise ValueError("--notion-parent-page-id is required for target notion")
        parent = normalize_notion_id(notion_parent_page_id)
        if parent is None:
            raise ValueError("Invalid parent_page_id")
        publish["notion"] = {"parent_page_id": parent}
    elif target == "confluence":
        if not (confluence_space_key or "").strip() or not (confluence_parent_title or "").strip():
            raise ValueError("--confluence-space-key and --confluence-parent-title are required for target confluence")
        publish["confluence"] = {"space_key": confluence_space_key.strip(),
                                 "parent_title": confluence_parent_title.strip()}
    with _locked():
        data = _read()
        if project_id not in data["projects"]:
            raise ValueError("unknown project_id")
        data["projects"][project_id]["publish"] = publish
        _write(data)
    return {"project_id": project_id, "publish": publish}


def show_publish(project_id: str) -> dict[str, Any]:
    if project_id not in _read()["projects"]:
        raise ValueError("unknown project_id")
    return {"project_id": project_id, "publish": get_publish(project_id)}


def resolve(ref: str | Path | None = None) -> ProjectContext:
    records = _read()["projects"]
    if isinstance(ref, str) and ref in records:
        record = records[ref]
        return ProjectContext(ref, config._resolve_project_path(record["path"]), record.get("verify_profile_id"))
    target = config._resolve_project_path(ref)
    common = _common_dir(target) if records else None
    for key, record in records.items():
        if record["path"] == str(target) or (common and common == record.get("git_common_dir")):
            return ProjectContext(key, target, record.get("verify_profile_id"))
    return ProjectContext(None, target)
