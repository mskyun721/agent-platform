"""Project-scoped native materialization with conservative ownership checks."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from agent_platform_mcp.tools import projects, skill_packages as packages

NATIVE = {"claude": ".claude/skills", "codex": ".agents/skills"}


def _project(project_id: str, data: dict) -> tuple[Path, dict]:
    if project_id not in data["projects"]:
        raise ValueError("registered project id required")
    context = projects.resolve(project_id)
    return context.path, data["projects"][project_id].setdefault("skills", {})


def _destination(project: Path, backend: str, skill_id: str) -> Path:
    path = project / NATIVE[backend] / packages.identifier(skill_id)
    packages.safe(path)
    return path


def _status(path: Path, content_hash: str, project_id: str, skill_id: str) -> str:
    try:
        packages.safe(path)
        if not path.exists():
            return "missing"
        marker = path / packages.MARKER
        packages.safe(marker)
        if not marker.is_file():
            return "unmanaged"
        ownership = json.loads(marker.read_text())
        if ownership != {"project_id": project_id, "id": skill_id, "hash": content_hash}:
            return "user_modified"
        return "applied" if packages.fingerprint(path, managed=True) == content_hash else "user_modified"
    except (ValueError, OSError):
        return "user_modified"


def _external(project: Path, skill_id: str) -> list[str]:
    # Presence-only discovery, never read global/plugin configuration or contents.
    roots = [Path.home() / ".claude/skills", Path.home() / ".agents/skills",
             Path.home() / ".codex/skills", Path("/etc/codex/skills")]
    for parent in project.parents:
        roots.extend(parent / rel for rel in NATIVE.values())
    return sorted({str(root / skill_id) for root in roots if (root / skill_id).exists()})


def enable(skill_id: str, project_id: str) -> dict:
    packages.identifier(skill_id)
    with projects._locked():
        registry = packages.read()["packages"]
        if skill_id not in registry:
            raise ValueError("unknown skill id")
        data = projects._read()
        project, state = _project(project_id, data)
        record = registry[skill_id]
        if skill_id in state:
            raise RuntimeError("skill already has managed state; disable first")
        for dep in record["depends_on"]:
            binding = state.get(dep, {})
            if not binding.get("enabled") or not set(record["supports"]).issubset(binding.get("materialized", {})):
                raise RuntimeError(f"dependency not enabled for requested backends: {dep}")
            for backend in record["supports"]:
                if _status(_destination(project, backend, dep), binding["hash"], project_id, dep) != "applied":
                    raise RuntimeError(f"dependency not applied: {dep}")
        source = packages.PACKAGES / skill_id
        if packages.fingerprint(source) != record["content_hash"]:
            raise RuntimeError("package user_modified; import as a new id")
        paths = {backend: _destination(project, backend, skill_id) for backend in record["supports"]}
        if any(path.exists() for path in paths.values()):
            raise FileExistsError("native skill already exists; unmanaged files preserved")
        created = []
        parents = []
        try:
            for path in paths.values():
                node = path.parent
                while not node.exists():
                    parents.append(node)
                    node = node.parent
                path.parent.mkdir(parents=True, exist_ok=True)
                created.append(path)
                shutil.copytree(source, path)
                if packages.fingerprint(path) != record["content_hash"]:
                    raise RuntimeError("package changed during materialization")
                (path / packages.MARKER).write_text(json.dumps({"project_id": project_id, "id": skill_id,
                                                             "hash": record["content_hash"]}))
            state[skill_id] = {"enabled": True, "hash": record["content_hash"],
                              "materialized": {backend: "applied" for backend in paths}}
            projects._write(data)
        except BaseException:
            for path in reversed(created):
                if path.exists():
                    shutil.rmtree(path)
            for path in sorted(set(parents), key=lambda p: len(p.parts), reverse=True):
                if path.exists():
                    path.rmdir()
            raise
        return {"id": skill_id, "project_id": project_id, **state[skill_id], "applies": "next_session",
                "source": "expected", "required_tools_unverified": record["requires_tools"],
                "external_active": _external(project, skill_id), "external_discovery": "partial"}


def disable(skill_id: str, project_id: str) -> dict:
    packages.identifier(skill_id)
    with projects._locked():
        data = projects._read()
        project, state = _project(project_id, data)
        if skill_id not in state:
            raise ValueError("skill has no managed state in this project")
        registry = packages.read()["packages"]
        dependents = [key for key, binding in state.items() if binding.get("enabled") and
                      skill_id in registry.get(key, {}).get("depends_on", [])]
        if dependents:
            raise RuntimeError(f"dependent skills enabled: {dependents}")
        binding = state[skill_id]
        statuses = {backend: _status(_destination(project, backend, skill_id), binding["hash"], project_id, skill_id)
                    for backend in binding["materialized"]}
        moved = []
        with tempfile.TemporaryDirectory(prefix=".agent-skill-disable-", dir=project) as temp:
            try:
                for backend, status in statuses.items():
                    if status == "applied":
                        path = _destination(project, backend, skill_id)
                        backup = Path(temp) / backend
                        path.rename(backup)
                        moved.append((path, backup))
                        statuses[backend] = "removed"
                retained = {key: value for key, value in statuses.items() if value not in {"removed", "missing"}}
                if retained:
                    binding.update(enabled=False, materialized=retained)
                else:
                    del state[skill_id]
                projects._write(data)
            except BaseException:
                for path, backup in reversed(moved):
                    backup.rename(path)
                raise
        external = _external(project, skill_id)
        return {"id": skill_id, "project_id": project_id, "enabled": False, "materialized": statuses,
                "complete": not retained and not external, "managed_removed": not retained,
                "applies": "next_session", "external_active": external,
                "external_discovery": "partial"}


def list_skills(project_id: str | None = None) -> dict:
    result = packages.list_skills(project_id)
    if project_id is None:
        return result
    project = projects.resolve(project_id).path
    for item in result["packages"]:
        binding = item["project_state"] or {}
        item["native"] = {backend: _status(_destination(project, backend, item["id"]),
                                           binding.get("hash", item["content_hash"]), project_id, item["id"])
                          for backend in NATIVE}
        item["external_active"] = _external(project, item["id"])
        item["shadowed"] = bool(item["external_active"]) or "unmanaged" in item["native"].values()
    result.update(external_discovery="partial", applies="next_session")
    return result


def active_versions(project_id: str, backend: str, root: Path | None = None) -> dict:
    if backend not in NATIVE:
        raise ValueError("unknown skill backend")
    if root is not None and root != projects.resolve(project_id).path:
        return {"skill_versions": {}, "skill_versions_source": "expected", "observed_usage": "unavailable",
                "warning": "skills are materialized at the registered path, not this worktree"}
    result = list_skills(project_id)
    versions = {item["id"]: item["content_hash"] for item in result["packages"]
                if (item["project_state"] or {}).get("enabled") and item["native"][backend] == "applied" and not item["shadowed"]}
    return {"skill_versions": versions, "skill_versions_source": "expected", "observed_usage": "unavailable"}
