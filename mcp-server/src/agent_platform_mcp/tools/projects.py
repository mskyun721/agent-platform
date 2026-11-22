"""Local project registry: the single place for targets, the default and workspaces.

`.agent-projects.json` (git-ignored, local only), schema v2::

    {"version": 2, "default": <project_id|null>, "default_path": <abs dir|null>,
     "env_fallback": <bool>, "workspaces": [<abs dir>...],
     "projects": {<project_id>: {"path", "git_common_dir", "verify_profile_id",
                                 "registered_at", "skills"?, "publish"?}}}

`default_path` keeps a worktree of the default project as the default checkout (the
requested path is kept, never silently swapped for the registered one).
`env_fallback: false` (written by `project-migrate` and `project-workspace add`)
permanently stops the deprecated env roots from becoming workspaces again.

A v1 file (`{"schema": 1, "projects": {...}}`) is read as v2 with no default and no
workspaces and is upgraded on the next write. Workspaces are changed and paths
outside them are registered only from the CLI, by the user; MCP tools stay inside them.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager, nullcontext
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


def _empty() -> dict[str, Any]:
    return {"version": 2, "default": None, "default_path": None, "env_fallback": True,
            "workspaces": [], "projects": {}}


def _read() -> dict[str, Any]:
    _safe_storage(REGISTRY_FILE)
    if not REGISTRY_FILE.exists():
        return _empty()
    data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("projects"), dict):
        raise ValueError("unsupported project registry schema")
    if type(data.get("version")) is int and data["version"] == 2:
        pass
    elif "version" not in data and type(data.get("schema")) is int and data["schema"] == 1:
        data = {**_empty(), "projects": data["projects"]}
    else:
        raise ValueError("unsupported project registry schema")
    for key, record in data["projects"].items():
        if not ID_RE.fullmatch(key) or not isinstance(record, dict):
            raise ValueError("invalid project registry record")
        if not isinstance(record.get("path"), str) or not Path(record["path"]).is_absolute():
            raise ValueError("registered project path must be absolute")
        for field in ("git_common_dir", "verify_profile_id"):
            if record.get(field) is not None and not isinstance(record[field], str):
                raise ValueError(f"invalid project registry {field}")
    spaces = data.get("workspaces", [])
    if not isinstance(spaces, list) or any(not isinstance(p, str) or not Path(p).is_absolute() for p in spaces):
        raise ValueError("registry workspaces must be absolute paths")
    default = data.get("default")
    if default is not None and default not in data["projects"]:
        raise ValueError("registry default is not a registered project")
    default_path = data.get("default_path")
    if default_path is not None and (default is None or not isinstance(default_path, str)
                                     or not Path(default_path).is_absolute()):
        raise ValueError("registry default_path must be an absolute path of the default project")
    fallback = data.get("env_fallback", True)
    if type(fallback) is not bool:
        raise ValueError("registry env_fallback must be true or false")
    return {"version": 2, "default": default, "default_path": default_path, "env_fallback": fallback,
            "workspaces": spaces, "projects": data["projects"]}


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


def _registrable(path: str | Path, trusted: bool) -> Path:
    """Where a project may be registered: the platform root or a workspace.

    `trusted` (CLI, a human) may also register any other existing directory, except
    while the deprecated env fallback is active (then registered paths grant nothing).
    """
    target = Path(path).expanduser().resolve()
    if not target.is_dir():
        raise FileNotFoundError(f"Project root is not a directory: {target}")
    if target == config.ROOT.resolve():
        return target
    if trusted and not config.env_fallback_active():
        return target
    return config.ensure_within_workspaces(target)


def _owner(data: dict[str, Any], target: Path, common: str | None) -> str | None:
    for key, record in data["projects"].items():
        if record["path"] == str(target) or (common and record.get("git_common_dir") == common):
            return key
    return None


def _derive_id(name: str, taken) -> str:
    base = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:60] or "project"
    if not base[0].isalpha():
        base = f"p-{base}"[:60]
    if len(base) < 2:
        base = f"{base}-project"
    candidate, number = base, 2
    while candidate in taken:
        candidate, number = f"{base}-{number}", number + 1
    return candidate


def _make_default(data: dict[str, Any], key: str, path: Path) -> None:
    """Default = `key`; a worktree (not the registered path) is kept as `default_path`."""
    data["default"] = key
    data["default_path"] = None if data["projects"][key]["path"] == str(path) else str(path)


def _record(target: Path, common: str | None, verify_profile: str | None) -> dict[str, Any]:
    return {"path": str(target), "git_common_dir": common, "verify_profile_id": verify_profile,
            "registered_at": datetime.now(timezone.utc).isoformat()}


def register(path: str, project_id: str | None = None, verify_profile: str | None = None,
             *, trusted: bool = False) -> dict[str, Any]:
    target = _registrable(path, trusted)
    project_id = project_id if project_id is not None else f"project-{uuid.uuid4().hex}"
    if not ID_RE.fullmatch(project_id):
        raise ValueError("project_id must be 2-64 lowercase letters, digits or dashes")
    if verify_profile is not None and verify_profile not in config.agent_config().get("verify_profiles", {}):
        raise ValueError("unknown verify profile")
    common = _common_dir(target)
    record = _record(target, common, verify_profile)
    with _locked():
        data = _read()
        if project_id in data["projects"]:
            raise ValueError("project_id already registered")
        if _owner(data, target, common):
            raise ValueError("project or worktree already registered; use its existing identity")
        data["projects"][project_id] = record
        _write(data)
    return {"project_id": project_id, **record}


def adopt(target: Path, project_id: str | None = None, make_default: bool = False) -> dict[str, Any]:
    """Register an already validated `target` (reusing its identity) and optionally make it the default.

    A derived ID is the folder name, with `-2`, `-3`... on collision; an explicit
    `project_id` that is taken by another project is an error.
    """
    if project_id is not None and not ID_RE.fullmatch(project_id):
        raise ValueError("project_id must be 2-64 lowercase letters, digits or dashes")
    common = _common_dir(target)
    legacy = config.legacy_active_file()
    with _locked():
        data = _read()
        key = _owner(data, target, common)
        reused = key is not None
        if key is None:
            if project_id in data["projects"]:
                raise ValueError("project_id already registered")
            key = project_id or _derive_id(target.name, data["projects"])
            data["projects"][key] = _record(target, common, None)
        elif project_id is not None and project_id != key:
            raise ValueError(f"path is already registered as '{key}'")
        if legacy is None and (make_default or data["default"] is None):
            _make_default(data, key, target)
        _write(data)
        default = data["default"] == key
    if legacy is not None:  # unmigrated checkout: the default still lives in .active-project
        if make_default or not config.active_projects():
            config.set_active_project(target)
        else:
            config.add_active_project(target)
        default = config.active_projects()[0] == target
    return {"project_id": key, "path": str(target), "reused": reused, "default": default}


def set_default_path(path: Path) -> str:
    """Make the project registered at `path` the default; it must be registered."""
    common = _common_dir(path)
    with _locked():
        data = _read()
        key = _owner(data, path, common)
        if key is None:
            raise ValueError(f"'{path}' is not a registered project; ask the user to run "
                             "`agent-platform-agent project-add <path>` (agents must not register projects)")
        _make_default(data, key, path)
        _write(data)
    return key


def _active_path() -> str | None:
    try:
        active = config.target_project_root()
    except RuntimeError:  # stale .active-project outside the allowlist
        return None
    return str(active) if active else None


def list_projects() -> dict[str, Any]:
    data = _read()
    records = data["projects"]
    active = _active_path()
    by_path = {value["path"]: key for key, value in records.items()}
    targets = [{"name": path.name, "path": str(path), "default": str(path) == active,
                "project_id": by_path.get(str(path)), "exists": path.is_dir()}
               for path in config.active_projects()]
    source = ("registry" if data["workspaces"] else
              "env" if data["env_fallback"] and config.env_project_roots() else "none")
    return {"version": 2, "default": data["default"], "default_path": data["default_path"],
            "workspaces": data["workspaces"], "workspace_source": source, "env_fallback": data["env_fallback"],
            "legacy_active_project": config.legacy_active_file() is not None,
            "active_path": active, "active_targets": targets,
            "projects": [{"project_id": key, **value, "publish": value.get("publish"), "active": value["path"] == active}
                         for key, value in sorted(records.items())]}


def use(ref: str, *, trusted: bool = False) -> dict[str, Any]:
    """Make a project the default target.

    `ref` is a registered project_id, a registered folder name or a path. It must be
    registered; only the CLI on an unmigrated checkout may still pick a target that is
    merely listed in .active-project.
    """
    context = resolve(ref)
    if context.path == config.ROOT.resolve():
        raise ValueError("the platform itself is selected with --root, not as the default target")
    if context.project_id is None and not (trusted and config.legacy_active_file() is not None):
        raise ValueError(f"'{ref}' is not a registered project; ask the user to run "
                         "`agent-platform-agent project-add <path>` (agents must not register projects)")
    config.set_active_project(context.path)  # enforces the allowlist
    return {"project_id": context.project_id, "path": str(context.path), "active": True,
            "active_targets": [str(path) for path in config.active_projects()]}


_GIT_URL = re.compile(r"(https://|ssh://|file://|git@[\w.-]+:)[\w./~:@%+-]+")


def _is_git_url(ref: str) -> bool:
    return bool(_GIT_URL.fullmatch(ref))


def _clone(url: str, into: str | None) -> Path:
    """Clone `url` into a workspace and return the checkout; reuse an existing clone."""
    parent = Path(into).expanduser().resolve() if into else config.allowed_project_roots()[0]
    name = url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1].removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ValueError("cannot derive a folder name from the repository URL")
    destination = config.ensure_within_workspaces(parent / name)
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


def add(ref: str, into: str | None = None, default: bool = False, project_id: str | None = None) -> dict[str, Any]:
    """Register a target from a local path or a git repository URL (CLI only).

    A URL is cloned into `into` (default: the first workspace) first — roles always
    work on a local checkout. An already registered path keeps its identity. The
    default changes only with `default` or when there is none. CLI-only on purpose:
    agents must not clone arbitrary remotes or register paths outside the workspaces.
    """
    cloned = _is_git_url(ref)
    path = _clone(ref, into) if cloned else _registrable(ref, trusted=True)
    if path == config.ROOT.resolve():
        raise ValueError("the platform itself is selected with --root, not listed as a target")
    result = adopt(path, project_id, default)
    return {**result, "cloned_from": ref if cloned else None,
            "active_targets": [str(entry) for entry in config.active_projects()]}


def _workspace_problem(target: Path) -> str | None:
    if target == Path(target.anchor):
        return "the filesystem root cannot be a workspace"
    if target == config.ROOT.resolve() or target.is_relative_to(config.ROOT.resolve()):
        return "a workspace cannot be or be inside the agent-platform checkout"
    return None


def _workspace_dir(path: str) -> Path:
    target = Path(path).expanduser().resolve()
    if not target.is_dir():
        raise FileNotFoundError(f"Workspace is not a directory: {target}")
    problem = _workspace_problem(target)
    if problem:
        raise ValueError(problem)
    return target


def _env_seed(data: dict[str, Any]) -> list[str]:
    """Deprecated env roots to import; nothing once the env fallback is off."""
    return [str(root) for root in config.env_project_roots()] if data["env_fallback"] else []


def workspace_add(path: str) -> dict[str, Any]:
    """CLI only. The first add also imports the deprecated env roots so none are silently dropped,
    then turns the env fallback off for good."""
    target = _workspace_dir(path)
    with _locked():
        data = _read()
        before = list(data["workspaces"])
        seeded = _env_seed(data) if not before else []
        for entry in (*seeded, str(target)):
            if entry not in data["workspaces"]:
                data["workspaces"].append(entry)
        if data["workspaces"] != before or data["env_fallback"]:
            data["env_fallback"] = False
            _write(data)
    return {"workspaces": data["workspaces"], "added": str(target) not in before,
            "imported_from_env": [entry for entry in seeded if entry not in before and entry != str(target)]}


def workspace_remove(path: str, allow_empty: bool = False) -> dict[str, Any]:
    """CLI only. Projects registered under it stay allowed until they are unregistered.
    Removing the last workspace needs `allow_empty`; the env fallback stays off either way."""
    target = str(Path(path).expanduser().resolve())
    with _locked():
        data = _read()
        if target not in data["workspaces"]:
            raise ValueError("not a registered workspace")
        if data["workspaces"] == [target] and not allow_empty:
            raise ValueError("refusing to remove the last workspace; pass --allow-empty to leave none")
        data["workspaces"].remove(target)
        data["env_fallback"] = False
        _write(data)
    still = sorted(key for key, record in data["projects"].items()
                   if Path(record["path"]).is_relative_to(target))
    return {"workspaces": data["workspaces"], "removed": target, "projects_still_registered": still}


def workspace_list() -> dict[str, Any]:
    data = _read()
    env = [str(root) for root in config.env_project_roots()]
    active = not data["workspaces"] and data["env_fallback"]
    return {"workspaces": data["workspaces"], "env_fallback": env if active else [],
            "env_fallback_allowed": data["env_fallback"], "env_deprecated": bool(env)}


def _migrated_name(legacy: Path) -> Path:
    candidate, number = legacy.with_name(legacy.name + ".migrated"), 2
    while candidate.exists():
        candidate, number = legacy.with_name(f"{legacy.name}.migrated.{number}"), number + 1
    return candidate


def migrate(dry_run: bool = False) -> dict[str, Any]:
    """Move .active-project and the deprecated env roots into the registry (CLI only, idempotent).

    Each listed line is registered (an existing identity is reused; a new ID is the
    folder name, `-2` on collision). The first usable line becomes the default; a
    worktree line is kept as `default_path` so the default checkout does not change.
    When the first line is skipped, `notices` says which later line became the default.
    Lines that are missing, the platform itself (or inside it), or outside the
    workspaces are skipped. The env value is read from the process environment only;
    .env is never read or edited. A real run turns the env fallback off for good and
    renames .active-project inside the registry lock; `dry_run` writes nothing.
    """
    legacy = config.ROOT / config._ACTIVE_PROJECT_FILE_NAME
    raw = legacy.read_text(encoding="utf-8") if legacy.is_file() else None
    lines = config._legacy_entries(legacy) if raw is not None else []
    commons = {path: _common_dir(path) for path in lines if path.is_dir()}
    registered, reused, skipped, notices, first, first_path = [], [], [], [], None, None
    renamed = None
    with nullcontext() if dry_run else _locked():
        data = _read()
        seeded = _env_seed(data)
        spaces = [*data["workspaces"], *(root for root in seeded if root not in data["workspaces"])]
        records = dict(data["projects"])
        for index, path in enumerate(lines):
            relation = (None if path not in commons else "root" if path == config.ROOT.resolve() else
                        "inside" if path.is_relative_to(config.ROOT.resolve()) else None)
            reason = ("missing" if path not in commons else
                      "platform root" if relation == "root" else
                      "inside the platform root" if relation else None)
            key = None if reason else _owner({"projects": records}, path, commons[path])
            if reason is None and key is None:
                if not config._within(path, [Path(space) for space in spaces]):
                    reason = "outside workspaces"
                else:
                    key = _derive_id(path.name, records)
                    records[key] = _record(path, commons[path], None)
                    registered.append({"project_id": key, "path": str(path)})
            elif key is not None:
                worktree = records[key]["path"] != str(path)
                reused.append({"project_id": key, "path": str(path), **({"worktree_of": records[key]["path"]}
                                                                          if worktree else {})})
            if reason:
                skipped.append({"path": str(path), "reason": reason})
            if first is None and key is not None:
                first, first_path = key, path
                if index:
                    notices.append(f"the first .active-project line {lines[0]} was skipped ({skipped[0]['reason']}); "
                                   f"the default is now '{key}' ({path}). Ask the user to run "
                                   "`agent-platform-agent project-use <id>` to choose another.")
        new = {**data, "env_fallback": False, "workspaces": spaces, "projects": records}
        if first is not None:
            _make_default(new, first, first_path)
        changed = new != data
        if not dry_run:
            if changed:
                _write(new)
            if legacy.is_file():
                if legacy.read_text(encoding="utf-8") != raw:
                    raise RuntimeError(".active-project changed during the migration; run project-migrate again")
                renamed = _migrated_name(legacy)
                legacy.rename(renamed)
    would_rename = renamed if not dry_run else (_migrated_name(legacy) if raw is not None else None)
    outside = sorted(key for key, record in records.items() if Path(record["path"]) != config.ROOT.resolve()
                     and not config._within(Path(record["path"]), [Path(space) for space in spaces]))
    env_roots = config.env_project_roots()
    return {"dry_run": dry_run, "changed": changed or would_rename is not None, "default": new["default"],
            "default_path": new["default_path"],
            "workspaces": spaces, "workspaces_added": [root for root in spaces if root not in data["workspaces"]],
            "registered": registered, "reused": reused, "skipped": skipped, "notices": notices,
            "renamed": [str(legacy), str(would_rename)] if would_rename else None,
            "registered_outside_workspaces": outside,
            "notice": (f"Remove {config.ALLOW_ENV} from .env yourself: workspaces now live in .agent-projects.json"
                       if env_roots else None)}


def rebind(project_id: str, new_path: str, *, trusted: bool = False) -> dict[str, Any]:
    target = _registrable(new_path, trusted)
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
        if data["default"] == project_id:
            data["default_path"] = None  # the default follows the rebound path
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
        if data["default"] == project_id:
            data["default"], data["default_path"] = None, None
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
