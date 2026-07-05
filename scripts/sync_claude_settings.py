#!/usr/bin/env python3
"""Sync Claude local settings from agent-platform environment config."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

ENV_FILE_NAME = ".agent-platform.env"
LOCAL_SETTINGS = Path(".claude/settings.local.json")
ALLOW_ENV = "AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS"


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


def sync_settings(repo_root: Path) -> bool:
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
    args = parser.parse_args()

    changed = sync_settings(args.repo_root.resolve())
    if not args.quiet:
        print("synced" if changed else f"skipped: {ALLOW_ENV} is not configured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
