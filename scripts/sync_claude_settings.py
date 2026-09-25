#!/usr/bin/env python3
"""Sync Claude local settings and subagent models from agent-platform config.

- permissions: AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS -> .claude/settings.local.json
- models: .agent-config.json `claude_models` -> `model:` in .claude/agents/<role>.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

ENV_FILE_NAME = ".agent-platform.env"
LOCAL_SETTINGS = Path(".claude/settings.local.json")
ALLOW_ENV = "AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS"
AGENT_CONFIG = Path(".agent-config.json")
AGENTS_DIR = Path(".claude/agents")
_MODEL_LINE = re.compile(r"^model:[ \t]*\S+[ \t]*$", re.M)
ROLES = ("orchestrator", "planner", "backend", "reviewer", "security", "qa", "cicd", "investment", "quant", "investment-risk")
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


def load_allowed_roots(repo_root: Path) -> list[Path]:
    env_values = _parse_env_file(repo_root / ENV_FILE_NAME)
    raw = os.environ.get(ALLOW_ENV) or env_values.get(ALLOW_ENV, "")
    return _split_roots(raw)


def build_dynamic_settings(roots: list[Path]) -> dict[str, Any]:
    resolved = [str(root.resolve()) for root in roots]
    allow: list[str] = []
    for root in resolved:
        allow.extend([f"Read({root}/**)", f"Write({root}/**)", f"Edit({root}/**)"])
    return {
        "permissions": {
            "additionalDirectories": resolved,
            "allow": allow,
        }
    }


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


def _merge_settings(existing: dict[str, Any], dynamic: dict[str, Any]) -> dict[str, Any]:
    result = dict(existing)
    permissions = dict(result.get("permissions") or {})
    dynamic_permissions = dynamic.get("permissions") or {}
    permissions["additionalDirectories"] = _merge_unique(
        list(permissions.get("additionalDirectories") or []),
        list(dynamic_permissions.get("additionalDirectories") or []),
    )
    permissions["allow"] = _merge_unique(
        list(permissions.get("allow") or []),
        list(dynamic_permissions.get("allow") or []),
    )
    result["permissions"] = permissions
    return result


def sync_agent_models(repo_root: Path, models: dict[str, str]) -> list[str]:
    """Write `claude_models` into each subagent's front-matter `model:` line.

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
    models = _read_json(repo_root / AGENT_CONFIG).get("claude_models") or {}
    if isinstance(models, dict):
        sync_agent_models(repo_root, models)
    sync_agent_bodies(repo_root)

    roots = load_allowed_roots(repo_root)
    if not roots:
        return False
    local_path = repo_root / LOCAL_SETTINGS
    local_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_json(local_path)
    updated = _merge_settings(existing, build_dynamic_settings(roots))
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
        changed = sync_agent_bodies(repo, check=args.check)
        if args.agents_only and not args.check:
            models = _read_json(repo / AGENT_CONFIG).get("claude_models") or {}
            if isinstance(models, dict):
                changed = sorted(set(changed + sync_agent_models(repo, models)))
        if not args.quiet:
            print(("drift: " if args.check else "synced: ") + ", ".join(changed) if changed else "up to date")
        return 1 if args.check and changed else 0

    changed = sync_settings(args.repo_root.resolve())
    if not args.quiet:
        print("synced" if changed else f"skipped: {ALLOW_ENV} is not configured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
