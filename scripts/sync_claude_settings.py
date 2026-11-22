#!/usr/bin/env python3
"""Sync Claude local settings and subagent models from agent-platform config.

- permissions: .agent-projects.json workspaces + registered project paths -> .claude/settings.local.json
  (the deprecated AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS only while the registry has no workspaces
  and was never migrated; a migrated checkout without a registry gets none). Stale generated
  grants are pruned, `/`, the checkout and its ancestors are never granted, and Edit/Write
  deny rules protect the boundary files.
  A registry that exists but cannot be parsed is an error, never an env fallback.
- models: .agent-config.json `role_tiers` x `model_tiers.<tier>.claude`, then the legacy per-role
  `claude_models` overrides -> `model:` in .claude/agents/<role>.md
- hooks: the Stop/SessionEnd `observe collect` launcher entries in the tracked .claude/settings.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ENV_FILE_NAME = ".env"
LEGACY_ENV_FILE_NAMES = (".agent-platform.env", ".env.local")  # read-only fallback
LOCAL_SETTINGS = Path(".claude/settings.local.json")
ALLOW_ENV = "AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS"
REGISTRY = Path(".agent-projects.json")
AGENT_CONFIG = Path(".agent-config.json")
AGENTS_DIR = Path(".claude/agents")
_MODEL_LINE = re.compile(r"^model:[ \t]*\S+[ \t]*$", re.M)
ROLES = ("orchestrator", "planner", "backend", "reviewer", "security", "dba", "qa", "cicd", "investment", "quant", "investment-risk")
MARKER = "<!-- generated from standards/agents/{role}.md; edit the source, then run scripts/sync_claude_settings.py --agents-only -->"
_FM = re.compile(r"\A---\r?\n.*?\r?\n---(?:\r?\n|$)", re.S)


def _safe_role_file(repo: Path, relative: Path) -> Path:
    repo = repo.resolve()
    path = repo / relative
    node = path
    while node != repo:
        if node.is_symlink():
            raise ValueError(f"role symlink not allowed: {relative}")
        node = node.parent
    return path


def canonical_body(repo: Path, role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"unknown role: {role}")
    path = _safe_role_file(repo, Path("standards/agents") / f"{role}.md")
    body = path.read_text(encoding="utf-8").strip()
    if not body:
        raise ValueError(f"empty role source: {role}")
    return body + "\n"


def generated_body(repo: Path, role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"unknown role: {role}")
    path = _safe_role_file(repo, AGENTS_DIR / f"{role}.md")
    text = path.read_text(encoding="utf-8")
    header = _FM.match(text)
    marker = MARKER.format(role=role) + "\n"
    if not header or not text[header.end():].startswith(marker):
        raise ValueError(f"missing generated marker or front-matter: {role}")
    return text[header.end() + len(marker):]


def sync_agent_bodies(repo: Path, *, check: bool = False) -> list[str]:
    pending = []
    for role in ROLES:
        source = _safe_role_file(repo, Path("standards/agents") / f"{role}.md")
        if not source.exists():
            continue
        path = _safe_role_file(repo, AGENTS_DIR / f"{role}.md")
        text = path.read_text(encoding="utf-8")
        header = _FM.match(text)
        if header is None:
            raise ValueError(f"agent front-matter missing: {role}")
        rendered = header.group(0).rstrip() + "\n" + MARKER.format(role=role) + "\n" + canonical_body(repo, role)
        if rendered != text:
            pending.append((path, rendered))
    # Validate all sources and adapter headers before changing any file.
    if not check:
        for path, rendered in pending:
            path.write_text(rendered, encoding="utf-8")
    return sorted(path.name for path, _ in pending)


PROJECT_SETTINGS = Path(".claude/settings.json")
COLLECT_SCRIPT = "scripts/hooks/observe_collect.py"
# Session-end collection: the launcher detaches `observe collect --root <platform>` and returns at once.
COLLECT_HOOK = {"hooks": [{"type": "command", "timeout": 5,
                           "command": f'python3 "${{CLAUDE_PROJECT_DIR}}/{COLLECT_SCRIPT}"'}]}
COLLECT_EVENTS = ("Stop", "SessionEnd")


def _is_collect(entry: Any) -> bool:
    return isinstance(entry, dict) and any(isinstance(hook, dict) and COLLECT_SCRIPT in str(hook.get("command"))
                                           for hook in entry.get("hooks") or [])


def sync_project_hooks(repo: Path, *, check: bool = False) -> list[str]:
    """Generate the Stop/SessionEnd collection hooks in the tracked .claude/settings.json.

    Agents never edit that file directly; this generator is the only writer of these entries.
    Other hooks are kept as they are; a stale generated entry is replaced in place."""
    path = _safe_role_file(repo, PROJECT_SETTINGS)
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    hooks = data.setdefault("hooks", {}) if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        raise ValueError(f"{PROJECT_SETTINGS} hooks must be an object")
    for event in COLLECT_EVENTS:
        entries = [entry for entry in hooks.get(event) or [] if not _is_collect(entry)]
        hooks[event] = [*entries, COLLECT_HOOK]
    rendered = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if rendered == text:
        return []
    if not check:
        path.write_text(rendered, encoding="utf-8")
    return [path.name]


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _split_roots(raw: str) -> list[Path]:
    parts: list[str] = []
    for chunk in raw.split(os.pathsep):
        parts.extend(p.strip() for p in chunk.split(","))
    return [Path(p).expanduser().resolve() for p in parts if p]


class RegistryError(ValueError):
    """.agent-projects.json exists but is unusable; permissions are not synced from anything else."""


# Files only the user may change; denied to Claude's Edit/Write by absolute path. The env
# files are exactly the ones the platform reads, so the tracked .env.example stays editable.
PROTECTED = (".agent-projects.json", ".agent-projects.lock", ENV_FILE_NAME, *LEGACY_ENV_FILE_NAMES,
             ".claude/settings*.json")
# Rules an earlier sync generated and no longer does; removed only on an exact match.
RETIRED = (".env*",)


def load_registry_roots(repo_root: Path) -> tuple[list[Path], list[Path], bool] | None:
    """(workspaces, registered project paths, env_fallback allowed); None when there is no registry."""
    path = repo_root / REGISTRY
    if path.is_symlink():
        raise RegistryError(f"{REGISTRY} must not be a symlink")
    if not path.exists():
        # After `project-migrate` a deleted registry means no roots, never the env (SECURITY F8).
        return ([], [], False) if any(repo_root.glob(".active-project.migrated*")) else None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RegistryError(f"{REGISTRY} cannot be read ({type(error).__name__}); fix it before syncing") from None
    if not isinstance(data, dict) or not isinstance(data.get("projects"), dict):
        raise RegistryError(f"{REGISTRY} has an unsupported schema")
    if data.get("version") == 2:
        spaces, fallback = data.get("workspaces", []), data.get("env_fallback", True)
    elif data.get("schema") == 1 and "version" not in data:
        spaces, fallback = [], True
    else:
        raise RegistryError(f"{REGISTRY} has an unsupported schema")
    if not isinstance(spaces, list) or any(not isinstance(p, str) or not Path(p).is_absolute() for p in spaces):
        raise RegistryError(f"{REGISTRY} workspaces must be absolute paths")
    if type(fallback) is not bool:
        raise RegistryError(f"{REGISTRY} env_fallback must be true or false")
    projects = [Path(r["path"]) for r in data["projects"].values()
                if isinstance(r, dict) and isinstance(r.get("path"), str) and Path(r["path"]).is_absolute()]
    return [Path(p) for p in spaces], projects, fallback


def _env_roots(repo_root: Path) -> list[Path]:
    env_values: dict[str, str] = {}
    for name in (*reversed(LEGACY_ENV_FILE_NAMES), ENV_FILE_NAME):  # .env wins
        env_values.update(_parse_env_file(repo_root / name))
    raw = os.environ.get(ALLOW_ENV) or env_values.get(ALLOW_ENV, "")
    return _split_roots(raw)


def _grantable(roots: list[Path], repo_root: Path) -> list[Path]:
    """Drop `/`, the checkout, anything inside it and its ancestors (warned on stderr)."""
    repo = repo_root.resolve()
    kept = []
    for root in roots:
        if root == Path(root.anchor) or root == repo or root.is_relative_to(repo) or repo.is_relative_to(root):
            print(f"sync_claude_settings: not granting {root} (filesystem root or agent-platform checkout)",
                  file=sys.stderr)
            continue
        kept.append(root)
    return list(dict.fromkeys(kept))


def load_allowed_roots(repo_root: Path) -> list[Path]:
    """The same scope the MCP server allows: registry workspaces + registered projects outside them.

    Without workspaces the registered projects still count (L-5), except while the
    deprecated env fallback is active (then only the env roots count, as in config).
    No registry at all: the deprecated env roots.
    """
    registry = load_registry_roots(repo_root)
    if registry is None:
        return _grantable(_env_roots(repo_root), repo_root)
    spaces, projects, fallback = registry
    if not spaces and fallback:
        env = _env_roots(repo_root)
        if env:
            return _grantable(env, repo_root)
    spaces = _grantable(spaces, repo_root)  # a rejected workspace must not hide projects under it
    extra = [p for p in projects if not any(p == s or p.is_relative_to(s) for s in spaces)]
    return [*spaces, *(p for p in _grantable(extra, repo_root) if p not in spaces)]


def _grant_rules(root: str) -> list[str]:
    return [f"Read({root}/**)", f"Write({root}/**)", f"Edit({root}/**)"]


def deny_rules(repo_root: Path, names: tuple[str, ...] = PROTECTED) -> list[str]:
    """Absolute (`//`) Edit/Write deny rules for the boundary files of this checkout."""
    repo = str(repo_root.resolve()).lstrip("/")
    return [f"{tool}(//{repo}/{name})" for name in names for tool in ("Edit", "Write")]


def build_dynamic_settings(roots: list[Path], repo_root: Path | None = None) -> dict[str, Any]:
    resolved = [str(root.resolve()) for root in roots]
    allow: list[str] = []
    for root in resolved:
        allow.extend(_grant_rules(root))
    permissions: dict[str, Any] = {"additionalDirectories": resolved, "allow": allow}
    if repo_root is not None:
        permissions["deny"] = deny_rules(repo_root)
        permissions["retired_deny"] = deny_rules(repo_root, RETIRED)
    return {"permissions": permissions}


def _merge_unique(existing: list[Any], additions: list[Any]) -> list[Any]:
    merged = list(existing)
    for item in additions:
        if item not in merged:
            merged.append(item)
    return merged


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _generated_directories(permissions: dict[str, Any]) -> set[str]:
    """Directories with exactly the generated shape: listed and granted Read+Write+Edit(<dir>/**)."""
    allow = set(permissions.get("allow") or [])
    return {d for d in permissions.get("additionalDirectories") or []
            if isinstance(d, str) and all(rule in allow for rule in _grant_rules(d))}


def _merge_settings(existing: dict[str, Any], dynamic: dict[str, Any]) -> dict[str, Any]:
    """Replace the generated grants (stale ones are pruned), keep everything else; deny only grows."""
    result = dict(existing)
    permissions = dict(result.get("permissions") or {})
    dynamic_permissions = dynamic.get("permissions") or {}
    fresh = list(dynamic_permissions.get("additionalDirectories") or [])
    stale = _generated_directories(permissions) - set(fresh)
    stale_rules = {rule for directory in stale for rule in _grant_rules(directory)}
    permissions["additionalDirectories"] = _merge_unique(
        [d for d in permissions.get("additionalDirectories") or [] if d not in stale], fresh)
    permissions["allow"] = _merge_unique(
        [rule for rule in permissions.get("allow") or [] if rule not in stale_rules],
        list(dynamic_permissions.get("allow") or []),
    )
    if dynamic_permissions.get("deny"):
        retired = set(dynamic_permissions.get("retired_deny") or [])
        kept = [rule for rule in permissions.get("deny") or [] if rule not in retired]
        permissions["deny"] = _merge_unique(kept, dynamic_permissions["deny"])
    result["permissions"] = permissions
    return result


def role_models(config: dict[str, Any], backend: str, overrides: Any = None) -> dict[str, str]:
    """{role: model} for one backend: role_tiers -> model_tiers[tier][backend], then per-role overrides."""
    tiers, assigned = config.get("model_tiers") or {}, config.get("role_tiers") or {}
    if not isinstance(tiers, dict) or not isinstance(assigned, dict):
        raise ValueError("model_tiers and role_tiers must be objects")
    models = {}
    for role, tier in assigned.items():
        models_for_tier = tiers.get(tier) if isinstance(tier, str) else None
        model = models_for_tier.get(backend) if isinstance(models_for_tier, dict) else None
        if model:
            models[role] = model
    if isinstance(overrides, dict):
        models.update({role: model for role, model in overrides.items() if model})
    return models


def claude_role_models(config: dict[str, Any]) -> dict[str, str]:
    return role_models(config, "claude", config.get("claude_models"))


def sync_agent_models(repo_root: Path, models: dict[str, str]) -> list[str]:
    """Write the resolved Claude role models into each subagent's front-matter `model:` line.

    Only the model line changes; tools/description/body are untouched. Roles
    without an agent file are ignored. Returns the file names that changed.
    """
    changed: list[str] = []
    for role, model in models.items():
        if not isinstance(role, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", role):
            raise ValueError("invalid agent role name")
        if not isinstance(model, str) or not model:
            continue
        if not re.fullmatch(r"[a-zA-Z0-9._/-]+", model):
            raise ValueError("invalid model identifier")
        path = _safe_role_file(repo_root, AGENTS_DIR / f"{role}.md")
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        header = _FM.match(text)
        if header is None:
            raise ValueError(f"agent front-matter missing: {role}")
        new = _MODEL_LINE.sub(lambda _: f"model: {model}", header.group(0), count=1) + text[header.end():]
        if new != text:
            path.write_text(new, encoding="utf-8")
            changed.append(path.name)
    return sorted(changed)


def sync_settings(repo_root: Path) -> bool:
    """Sync permissions (when roots are configured) and subagent models.
    Returns True when the permissions file was written."""
    sync_agent_models(repo_root, claude_role_models(_read_json(repo_root / AGENT_CONFIG)))
    sync_agent_bodies(repo_root)
    sync_project_hooks(repo_root)

    roots = load_allowed_roots(repo_root)  # raises RegistryError on a damaged registry
    local_path = repo_root / LOCAL_SETTINGS
    existing = _read_json(local_path)
    if not roots and not _generated_directories(existing.get("permissions") or {}):
        return False
    local_path.parent.mkdir(parents=True, exist_ok=True)
    updated = _merge_settings(existing, build_dynamic_settings(roots, repo_root))
    local_path.write_text(
        json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return True


def _default_repo_root() -> Path:
    here = Path(__file__).resolve()
    return here.parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=_default_repo_root())
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--agents-only", action="store_true", help="Sync role adapters without reading environment or permission files")
    parser.add_argument("--check", action="store_true", help="Check generated role bodies without writing any files")
    args = parser.parse_args()

    if args.check or args.agents_only:
        repo = args.repo_root.resolve()
        changed = sync_agent_bodies(repo, check=args.check) + sync_project_hooks(repo, check=args.check)
        if args.agents_only and not args.check:
            models = claude_role_models(_read_json(repo / AGENT_CONFIG))
            changed = sorted(set(changed + sync_agent_models(repo, models)))
        if (repo / ".mcp.json").is_file():  # host adapters need the shared MCP source
            import sync_hosts
            changed = sorted(set(changed) | set(sync_hosts.sync_all(repo, check=args.check)))
        if not args.quiet:
            print(("drift: " if args.check else "synced: ") + ", ".join(changed) if changed else "up to date")
        return 1 if args.check and changed else 0

    try:
        changed = sync_settings(args.repo_root.resolve())
    except RegistryError as error:
        print(f"sync_claude_settings: {error}", file=sys.stderr)
        return 1
    if not args.quiet:
        print("synced" if changed else "skipped: no workspace (the user runs agent-platform-agent project-workspace add <dir>)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
