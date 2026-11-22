"""Per-feature token usage, per-type/role statistics and advisory budgets.

Read-only over the existing runs/usage/review_results/events tables and the feature's
docs front-matter. Results carry counts and identifiers only (BR-8). Backends are never
summed together (A-4) and unmeasured usage is never filled with zero (BR-5).
"""

from __future__ import annotations

from pathlib import Path

from agent_platform_mcp import config, events, frontmatter
from agent_platform_mcp.tools.feature import canonical_feature, safe_path

TYPES = ("work", "light", "full")


def _positive(value) -> bool:
    return type(value) is int and value > 0


def load_budget(settings: dict | None = None) -> dict:
    """`.agent-config.json` `token_budget`; absent keys mean no budget (no defaults, Q-2)."""
    raw = (settings if settings is not None else config.agent_config()).get("token_budget")
    if raw is None:
        return {"types": {}, "roles": {}}
    if not isinstance(raw, dict):
        raise ValueError("invalid token_budget: token_budget")
    for key in raw:
        if key not in {"types", "roles"} and not key.startswith("_"):
            raise ValueError(f"invalid token_budget: {key}")
    budget = {}
    for section, allowed in (("types", set(TYPES)), ("roles", events.ROLES)):
        values = raw.get(section, {})
        if not isinstance(values, dict):
            raise ValueError(f"invalid token_budget: {section}")
        for key, value in values.items():
            if key not in allowed or not _positive(value):
                raise ValueError(f"invalid token_budget: {section}.{key}")
        budget[section] = dict(values)
    return budget


def feature_kind(project: Path, key: str) -> dict:
    """Work type (gate_check's track rule, A-2) and completion (A-3) of one feature folder.

    completed: every cicd output of the track is approved, or WORK/PRD front-matter has
    `archived: true`. A missing folder reports exists=False and type None."""
    name = canonical_feature(key)
    target = config.docs_dir(name, project_dir=project)
    safe_path(target, project)
    if not target.is_dir():
        return {"feature": display_key(name), "exists": False, "type": None, "completed": False}
    kind = "work" if (target / "WORK.md").is_file() else (
        "light" if name.startswith(config.LIGHT_TRACK_PREFIXES) else "full")
    completed = False
    for anchor in ("WORK.md", "PRD.md"):
        path = target / anchor
        safe_path(path, project)
        if str((frontmatter.read(path) or {}).get("archived", "")).lower() == "true":
            completed = True
    if not completed:
        outputs = config.AGENT_OUTPUTS_BY_TRACK[kind]["cicd"]
        statuses = []
        for output in outputs:
            path = target / output
            safe_path(path, project)
            statuses.append((frontmatter.read(path) or {}).get("status"))
        completed = bool(outputs) and all(status == "approved" for status in statuses)
    return {"feature": display_key(name), "exists": True, "type": kind, "completed": completed}


def display_key(name: str) -> str:
    """`<type>/<name>`: run task ids store bare names for docs/features (canonical_feature)."""
    return name if "/" in name else f"features/{name}"
