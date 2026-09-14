"""Local, non-executing skill snapshots. Project activation lives in skills.py."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from agent_platform_mcp import config, frontmatter
from agent_platform_mcp.tools import projects

PACKAGES = config.ROOT / "skills/packages"
REGISTRY = config.ROOT / "skills/registry.json"
MARKER = ".agent-platform-managed"


def identifier(value: str) -> str:
    if not isinstance(value, str) or not projects.ID_RE.fullmatch(value):
        raise ValueError("skill id must be 2-64 lowercase letters, digits or dashes")
    return value


def safe(path: Path) -> None:
    projects._safe_storage(path)


def fingerprint(directory: Path, *, managed: bool = False) -> str:
    safe(directory)
    if not directory.is_dir():
        raise ValueError("skill package directory missing")
    manifest = {}
    total = 0
    for path in sorted(directory.rglob("*")):
        safe(path)
        rel = path.relative_to(directory).as_posix()
        if managed and rel == MARKER:
            continue
        if any(part.startswith(".") or any(word in part.lower() for word in
               ("credential", "secret", ".pem", ".key")) for part in path.relative_to(directory).parts):
            raise ValueError("hidden or protected files cannot be packaged")
        mode = path.stat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError("skill resources must be regular files")
        total += path.stat().st_size
        if total > 64 * 1024 * 1024 or len(manifest) >= 2000:
            raise ValueError("skill package exceeds resource limits")
        manifest[rel] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "executable": mode & 0o111}
    return hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()


def read() -> dict:
    safe(REGISTRY)
    if not REGISTRY.exists():
        return {"schema": 1, "packages": {}}
    data = json.loads(REGISTRY.read_text())
    if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 1 or not isinstance(data.get("packages"), dict):
        raise ValueError("unsupported skill registry schema")
    for key, record in data["packages"].items():
        identifier(key)
        if not isinstance(record, dict) or not isinstance(record.get("content_hash"), str):
            raise ValueError("invalid skill record")
        metadata = {**record, "id": key}
        validate_metadata(metadata)
    return data


def write(data: dict) -> None:
    safe(REGISTRY)
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=REGISTRY.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump(data, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, REGISTRY)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def validate_metadata(data: dict) -> None:
    if not isinstance(data, dict):
        raise ValueError("skill.json must be an object")
    identifier(data.get("id"))
    if not isinstance(data.get("version"), str) or not data["version"].strip():
        raise ValueError("skill version required")
    for key in ("supports", "depends_on", "requires_tools"):
        values = data.get(key, [] if key != "supports" else None)
        if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values) or len(set(values)) != len(values):
            raise ValueError(f"{key} must be a unique string list")
    if not data["supports"] or set(data["supports"]) - {"claude", "codex"}:
        raise ValueError("supports must contain claude or codex")
    for dep in data.get("depends_on", []):
        identifier(dep)
        if dep == data["id"]:
            raise ValueError("skill cannot depend on itself")


def add(path: str) -> dict:
    source = Path(os.path.abspath(path))
    content_hash = fingerprint(source)
    metadata = json.loads((source / "skill.json").read_text())
    validate_metadata(metadata)
    fm = frontmatter.read(source / "SKILL.md") or {}
    if fm.get("name") != metadata["id"] or not isinstance(fm.get("description"), str) or not fm["description"].strip():
        raise ValueError("SKILL.md requires matching name and description")
    skill_id = metadata["id"]
    with projects._locked():
        data = read()
        if skill_id in data["packages"]:
            raise FileExistsError("skill id exists; remove first or use a new id")
        missing = set(metadata.get("depends_on", [])) - data["packages"].keys()
        if missing:
            raise ValueError(f"missing dependency packages: {sorted(missing)}")
        safe(PACKAGES)
        destination = PACKAGES / skill_id
        safe(destination)
        if destination.exists():
            raise FileExistsError("unregistered package directory exists; preserved")
        PACKAGES.mkdir(parents=True, exist_ok=True)
        record = {key: metadata.get(key, []) for key in ("version", "supports", "depends_on", "requires_tools")}
        record.update(source=f"local:{source}", content_hash=content_hash,
                      description=fm["description"], owner="agent-platform",
                      added_at=datetime.now(timezone.utc).isoformat())
        try:
            shutil.copytree(source, destination)
            if fingerprint(destination) != content_hash:
                raise ValueError("source changed during import")
            data["packages"][skill_id] = record
            write(data)
        except BaseException:
            if destination.exists():
                shutil.rmtree(destination)
            raise
    return {"id": skill_id, **record}


def remove(skill_id: str) -> dict:
    identifier(skill_id)
    with projects._locked():
        data = read()
        if skill_id not in data["packages"]:
            raise ValueError("unknown skill id")
        dependents = [key for key, value in data["packages"].items() if skill_id in value["depends_on"]]
        if dependents:
            raise RuntimeError(f"dependent packages: {dependents}")
        users = [key for key, record in projects._read()["projects"].items()
                 if skill_id in record.get("skills", {})]
        if users:
            raise RuntimeError(f"disable and clean managed copies in projects first: {users}")
        directory = PACKAGES / skill_id
        if fingerprint(directory) != data["packages"][skill_id]["content_hash"]:
            raise RuntimeError("package user_modified; preserved")
        with tempfile.TemporaryDirectory(prefix=".skill-remove-", dir=PACKAGES) as temp:
            backup = Path(temp) / skill_id
            directory.rename(backup)
            try:
                del data["packages"][skill_id]
                write(data)
            except BaseException:
                backup.rename(directory)
                raise
    return {"id": skill_id, "removed": True}


def list_skills(project_id: str | None = None) -> dict:
    with projects._locked():
        data = read()
        state = {}
        if project_id is not None:
            projects.resolve(project_id)
            record = projects._read()["projects"].get(project_id)
            if record is None:
                raise ValueError("registered project id required")
            state = record.get("skills", {})
        return {"packages": [{"id": key, **record, "project_state": state.get(key)}
                             for key, record in sorted(data["packages"].items())]}
