"""Per-feature token usage, per-type/role statistics and advisory budgets.

Read-only over the existing runs/usage/review_results/events tables and the feature's
docs front-matter. Results carry counts and identifiers only (BR-8). Backends are never
summed together (A-4) and unmeasured usage is never filled with zero (BR-5).
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from agent_platform_mcp import config, events, frontmatter
from agent_platform_mcp.tools import pricing, projects, store
from agent_platform_mcp.tools.feature import canonical_feature, safe_path

TYPES = ("work", "light", "full")
COUNTS = pricing.COUNTS
MIN_SAMPLE = 3
LIMITATIONS = [
    "Only runs recorded with the feature key as task_id are counted; earlier work has no usage records (A-5).",
    "Usage with completeness != full is excluded from sums and counted as missing; it is never zero-filled.",
    "Backends define input/cache tokens differently; totals are per backend and a single total exists only for one backend.",
    "Handoff/verification point records are not LLM executions and are excluded from run counts.",
    "Native session usage is not attributed to runs yet (unattributed_runs: null).",
]


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


def _since(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        day = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("since must be YYYY-MM-DD") from exc
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc).isoformat()


def _runs(db, context: projects.ProjectContext, since: str | None, task_id: str | None = None) -> list[dict]:
    """One joined scan (runs_project index); handoff/verification point runs are excluded."""
    rows = db.connection.execute(
        "SELECT r.run_id,r.task_id,r.event_json,u.payload_json FROM runs r LEFT JOIN usage u ON u.run_id=r.run_id "
        "WHERE r.project_id IS ? AND (? IS NULL OR r.started_at>=?) AND (? IS NULL OR r.task_id=?) "
        "AND r.run_id NOT IN (SELECT run_id FROM events WHERE event_type IN ('handoff','verification')) "
        "ORDER BY r.started_at,r.run_id", (context.project_id, since, since, task_id, task_id))
    result = []
    for run_id, task, event_json, usage_json in rows:
        event = json.loads(event_json)
        payload = event.get("payload") or {}
        if context.project_id is None and payload.get("workspace") != str(context.path):
            continue
        usage = json.loads(usage_json) if usage_json else None
        result.append({"run_id": run_id, "task_id": task, "role": event["role"], "backend": event.get("backend") or "unknown",
                       "model": event.get("model") or "unknown", "price": payload.get("price_snapshot"),
                       "usage": usage if usage and usage.get("completeness") == "full" else None})
    return result


def _tokens(runs: list[dict]) -> dict:
    sums = {}
    for key in COUNTS:
        known = [run["usage"][key] for run in runs if run["usage"] and run["usage"].get(key) is not None]
        sums[key] = sum(known) if known else None
    return sums


def _cost(runs: list[dict]) -> tuple[dict, int]:
    costs, missing = {}, 0
    for run in runs:
        try:
            value = pricing.estimate(run["usage"], run["price"])
        except ValueError:
            value = None
        if value is None:
            missing += 1
        else:
            currency = run["price"]["currency"]
            costs[currency] = costs.get(currency, Decimal(0)) + value
    return {key: str(value) for key, value in costs.items()}, missing


def aggregate(runs: list[dict]) -> dict:
    """BR-3/BR-5: per-backend sums, role run/rework counts; a total only for one backend."""
    by_backend_runs, by_role_runs = defaultdict(list), defaultdict(list)
    for run in runs:
        by_backend_runs[run["backend"]].append(run)
        by_role_runs[run["role"]].append(run)
    by_backend = {backend: {"runs": len(items), "missing": sum(run["usage"] is None for run in items),
                            "tokens": _tokens(items)} for backend, items in by_backend_runs.items()}
    by_role = {}
    for role, items in by_role_runs.items():
        inputs = {backend: _tokens([run for run in items if run["backend"] == backend])["input_tokens"]
                  for backend in sorted({run["backend"] for run in items})}
        by_role[role] = {"runs": len(items), "reworks": len(items) - 1, "missing": sum(run["usage"] is None for run in items),
                         "input_tokens": next(iter(inputs.values())) if len(inputs) == 1 else None,
                         "input_tokens_by_backend": inputs}
    cost, missing_cost = _cost(runs)
    return {"runs": len(runs), "by_backend": by_backend,
            "total": next(iter(by_backend.values()))["tokens"] if len(by_backend) == 1 else None,
            "by_role": by_role, "cost": cost, "missing_cost": missing_cost}


def _stats(values: list, digits: int = 0) -> dict | None:
    if not values:
        return None
    rounded = (lambda value: round(value)) if digits == 0 else (lambda value: round(value, digits))
    return {"mean": rounded(statistics.fmean(values)), "median": rounded(statistics.median(values)), "max": max(values)}


def feature_usage(context: projects.ProjectContext, key: str, since: str | None = None) -> dict:
    name = canonical_feature(key)
    kind = feature_kind(context.path, name)
    with store.open() as db:
        runs = _runs(db, context, _since(since), name)
    if not runs and not kind["exists"]:
        raise ValueError(f"no runs or docs for feature: {kind['feature']}")
    return {"feature": kind["feature"], "type": kind["type"], "completed": kind["completed"], "since": since,
            **aggregate(runs), "unattributed_runs": None, "limitations": LIMITATIONS}


def _features(context: projects.ProjectContext, since: str | None) -> dict[str, list[dict]]:
    grouped = defaultdict(list)
    with store.open() as db:
        for run in _runs(db, context, _since(since)):
            grouped[run["task_id"]].append(run)
    return grouped


def type_stats(context: projects.ProjectContext, since: str | None = None, include_incomplete: bool = False) -> dict:
    """BR-4: completed features only (unless include_incomplete); n<3 is insufficient_sample."""
    samples = {kind: [] for kind in TYPES}
    excluded = {"in_progress": 0, "no_docs": 0}
    for task, runs in _features(context, since).items():
        try:
            kind = feature_kind(context.path, task)
        except ValueError:
            kind = {"exists": False}
        if not kind["exists"]:
            excluded["no_docs"] += 1
        elif not kind["completed"] and not include_incomplete:
            excluded["in_progress"] += 1
        else:
            samples[kind["type"]].append(aggregate(runs))
    types = {}
    for kind, features in samples.items():
        if not features:
            types[kind] = {"n": 0, "status": "no_data"}
            continue
        types[kind] = {}
        for backend in sorted({backend for feature in features for backend in feature["by_backend"]}):
            used = [feature["by_backend"][backend] for feature in features if backend in feature["by_backend"]]
            entry = {"n": len(used), "missing_runs": sum(item["missing"] for item in used),
                     **{key: _stats([item["tokens"][key] for item in used if item["tokens"][key] is not None]) for key in COUNTS}}
            if len(used) < MIN_SAMPLE:
                entry["status"] = "insufficient_sample"
            types[kind][backend] = entry
    return {"scope": "all features" if include_incomplete else "completed features only", "since": since, "types": types,
            "in_progress_excluded": excluded["in_progress"], "no_docs_excluded": excluded["no_docs"], "limitations": LIMITATIONS}


def group_stats(context: projects.ProjectContext, by: str = "role", since: str | None = None) -> dict:
    """Per-run statistics per role (or model) x backend, including in-progress features."""
    field = {"role": "role", "model": "model"}[by]
    groups = defaultdict(list)
    for runs in _features(context, since).values():
        for run in runs:
            groups[(run[field], run["backend"])].append(run)
    result = defaultdict(dict)
    for (name, backend), runs in sorted(groups.items()):
        measured = [run["usage"] for run in runs if run["usage"]]
        entry = {"n": len(runs), "missing_runs": len(runs) - len(measured),
                 **{key: _stats([usage[key] for usage in measured if usage.get(key) is not None]) for key in COUNTS}}
        if len(runs) < MIN_SAMPLE:
            entry["status"] = "insufficient_sample"
        result[name][backend] = entry
    return {"scope": "all runs", "since": since, f"{by}s": dict(result), "limitations": LIMITATIONS}
