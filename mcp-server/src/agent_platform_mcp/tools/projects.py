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


def list_projects() -> dict[str, Any]:
    records = _read()["projects"]
    return {"schema": 1, "projects": [{"project_id": key, **value} for key, value in sorted(records.items())]}


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
