"""Per-feature token usage, per-type/role statistics and advisory budgets.

Read-only over the existing runs/usage/review_results/events tables and the feature's
docs front-matter. Results carry counts and identifiers only (BR-8). Backends are never
summed together (A-4) and unmeasured usage is never filled with zero (BR-5).
"""

from __future__ import annotations

import json
import os
import statistics
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from agent_platform_mcp import config, events, frontmatter
from agent_platform_mcp.tools import pricing, projects, store
from agent_platform_mcp.tools.feature import canonical_feature, safe_path
from agent_platform_mcp.tools.review_requests import review_request_rows

TYPES = ("work", "light", "full")
COUNTS = pricing.COUNTS
MIN_SAMPLE = 3
REVIEW_ROLES = ("reviewer", "security", "dba", "qa")
GATE_ROLES = ("backend", "reviewer", "security", "dba", "qa", "cicd")
UNKNOWN = "unknown"
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


def _quality_sources(db, context: projects.ProjectContext, task_id: str | None = None) -> dict:
    """review_results and handoff records per task, each read in one scan (BR-9, BR-10)."""
    sources = defaultdict(lambda: {"reviews": [], "handoffs": []})
    for task, payload in db.connection.execute(
            "SELECT task_id,payload_json FROM review_results WHERE project_id IS ? AND (? IS NULL OR task_id=?) ORDER BY rowid",
            (context.project_id, task_id, task_id)):
        sources[task]["reviews"].append(json.loads(payload))
    for task, run_json, event_json in db.connection.execute(
            "SELECT r.task_id,r.event_json,e.event_json FROM events e JOIN runs r ON r.run_id=e.run_id "
            "WHERE e.event_type='handoff' AND r.project_id IS ? AND (? IS NULL OR r.task_id=?) ORDER BY e.ts,e.rowid",
            (context.project_id, task_id, task_id)):
        if context.project_id is None and (json.loads(run_json).get("payload") or {}).get("workspace") != str(context.path):
            continue
        sources[task]["handoffs"].append(json.loads(event_json)["payload"])
    return sources


def _bugs(target: Path, project: Path):
    """BUG-*.md severity front-matter; no bugs/ and no TEST-PLAN.md means QA left no record."""
    folder = target / "bugs"
    if not folder.is_dir():
        return {"P0": 0, "P1": 0, "other": 0} if (target / "TEST-PLAN.md").is_file() else UNKNOWN
    counts = {"P0": 0, "P1": 0, "other": 0}
    for path in sorted(folder.glob("BUG-*.md")):
        safe_path(path, project)
        severity = str((frontmatter.read(path) or {}).get("severity", "")).strip().upper()
        counts[severity if severity in {"P0", "P1"} else "other"] += 1
    return counts


def _review_requests(target: Path, project: Path):
    found, decided = False, 0
    for file in ("PRD.md", "WORK.md", "REVIEW.md"):
        path = target / file
        safe_path(path, project)
        if path.is_file():
            found = True
            decided += sum(row["resolved"] for row in review_request_rows(path.read_text(encoding="utf-8")))
    return decided if found else UNKNOWN


def quality(context: projects.ProjectContext, name: str, sources: dict) -> dict:
    """Rejections/cycles, first-pass gates, QA bugs and human interventions; never a combined score."""
    reviews, handoffs = sources["reviews"], sources["handoffs"]
    rejections = {role: sum(row["decision"] == "rejected" for row in reviews if row["role"] == role)
                  if any(row["role"] == role for row in reviews) else UNKNOWN for role in REVIEW_ROLES}
    streaks, recommended = defaultdict(int), set()
    for row in reviews:
        streaks[row["role"]] = streaks[row["role"]] + 1 if row["decision"] == "rejected" else 0
        if streaks[row["role"]] >= 3:
            recommended.add(row["role"])
    first = {}
    for row in handoffs:
        if row.get("purpose") == "implementation_complete":
            first.setdefault(row.get("to_agent"), row.get("passed") is True)
    target = config.docs_dir(name, project_dir=context.path)
    safe_path(target, context.path)
    requests = _review_requests(target, context.path) if target.is_dir() else UNKNOWN
    return {"rejections": rejections, "review_cycles": max((row["attempt"] for row in reviews), default=UNKNOWN),
            "first_pass_gates": {role: first.get(role, UNKNOWN) for role in GATE_ROLES},
            "bugs": _bugs(target, context.path) if target.is_dir() else UNKNOWN,
            "human_interventions": requests if requests == UNKNOWN or not reviews else requests + len(recommended),
            "intervention_recommended": len(recommended) if reviews else UNKNOWN}


def _quality_scalars(item: dict, aggregate_result: dict) -> dict:
    known = [value for value in item["rejections"].values() if value != UNKNOWN]
    return {"reworks": sum(role["reworks"] for role in aggregate_result["by_role"].values()),
            "rejections": sum(known) if known else UNKNOWN, "review_cycles": item["review_cycles"],
            "bugs": sum(item["bugs"].values()) if item["bugs"] != UNKNOWN else UNKNOWN,
            "human_interventions": item["human_interventions"],
            "first_pass": [value for value in item["first_pass_gates"].values() if value != UNKNOWN]}


def _quality_stats(rows: list[dict]) -> dict:
    """Mean/median per metric over features where it is known; first-pass as a passed/known ratio."""
    result = {}
    for metric in ("reworks", "rejections", "review_cycles", "bugs", "human_interventions"):
        values = [row[metric] for row in rows if row[metric] != UNKNOWN]
        result[metric] = {"n": len(values), **(_stats(values, 2) or {})}
    gates = [value for row in rows for value in row["first_pass"]]
    result["first_pass_gates"] = {"n": len(gates), "passed": sum(gates)}
    return result


def budget_status(kind: str | None, result: dict, runs: list[dict], settings: dict | None = None) -> dict:
    """BR-6: advisory input-token budget. over/within/unknown; never changes gate results."""
    status = {"status": UNKNOWN, "feature_input_tokens": None, "limit": None, "role_over": []}
    try:
        budget = load_budget(settings)
    except ValueError as exc:
        return {**status, "reason": str(exc)}
    limit = budget["types"].get(kind) if kind else None
    used = result["total"]["input_tokens"] if result["total"] else None
    roles = budget["roles"]
    role_over = sorted({run["role"] for run in runs if run["usage"] and run["role"] in roles
                        and (run["usage"].get("input_tokens") or 0) > roles[run["role"]]})
    status.update(feature_input_tokens=used, limit=limit, role_over=role_over)
    missing = sum(item["missing"] for item in result["by_backend"].values())
    if (limit is not None and used is not None and used > limit) or role_over:
        return {**status, "status": "over"}
    if limit is None and not roles:
        return {**status, "reason": "no token_budget for this type or roles"}
    if not runs:
        return {**status, "reason": "no runs recorded"}
    if limit is not None and result["total"] is None:
        return {**status, "reason": "multiple backends; no single total"}
    if missing or (limit is not None and used is None):
        return {**status, "reason": "missing measurements"}
    if limit is None and not any(run["role"] in roles for run in runs):
        return {**status, "reason": "no runs of budgeted roles"}
    return {**status, "status": "within"}


def gate_usage(context: projects.ProjectContext, name: str, track: str) -> dict:
    """gate/handoff `usage` key. Opens no state DB unless a budget is configured and the DB exists."""
    try:
        if load_budget() == {"types": {}, "roles": {}}:
            return budget_status(track, {"total": None, "by_backend": {}}, [], {})
        if not Path(os.environ.get("AGENT_PLATFORM_STATE_DB", config.ROOT / ".local/state.db")).is_file():
            return {"status": UNKNOWN, "feature_input_tokens": None, "limit": None, "role_over": [], "reason": "no usage records"}
        with store.open() as db:
            runs = _runs(db, context, None, canonical_feature(name))
        return budget_status(track, aggregate(runs), runs)
    except ValueError as exc:
        return {"status": UNKNOWN, "feature_input_tokens": None, "limit": None, "role_over": [], "reason": str(exc)}
    except Exception as exc:  # advisory only: never break a gate
        return {"status": UNKNOWN, "feature_input_tokens": None, "limit": None, "role_over": [], "reason": type(exc).__name__}


def feature_usage(context: projects.ProjectContext, key: str, since: str | None = None) -> dict:
    name = canonical_feature(key)
    kind = feature_kind(context.path, name)
    with store.open() as db:
        runs = _runs(db, context, _since(since), name)
        sources = _quality_sources(db, context, name)[name]
    if not runs and not kind["exists"]:
        raise ValueError(f"no runs or docs for feature: {kind['feature']}")
    result = aggregate(runs)
    return {"feature": kind["feature"], "type": kind["type"], "completed": kind["completed"], "since": since,
            **result, "quality": quality(context, name, sources), "unattributed_runs": None,
            "budget": budget_status(kind["type"], result, runs), "limitations": LIMITATIONS}


def _features(context: projects.ProjectContext, since: str | None, sources: bool = False):
    grouped = defaultdict(list)
    with store.open() as db:
        for run in _runs(db, context, _since(since)):
            grouped[run["task_id"]].append(run)
        return (grouped, _quality_sources(db, context)) if sources else grouped


def type_stats(context: projects.ProjectContext, since: str | None = None, include_incomplete: bool = False) -> dict:
    """BR-4: completed features only (unless include_incomplete); n<3 is insufficient_sample."""
    samples = {kind: [] for kind in TYPES}
    qualities = {kind: [] for kind in TYPES}
    excluded = {"in_progress": 0, "no_docs": 0}
    grouped, sources = _features(context, since, sources=True)
    for task, runs in grouped.items():
        try:
            kind = feature_kind(context.path, task)
        except ValueError:
            kind = {"exists": False}
        if not kind["exists"]:
            excluded["no_docs"] += 1
        elif not kind["completed"] and not include_incomplete:
            excluded["in_progress"] += 1
        else:
            result = aggregate(runs)
            samples[kind["type"]].append(result)
            qualities[kind["type"]].append(_quality_scalars(quality(context, task, sources[task]), result))
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
            "quality": {kind: _quality_stats(rows) for kind, rows in qualities.items() if rows},
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


def report(root: str, feature: str | None = None, by: str | None = None, since: str | None = None,
           include_incomplete: bool = False) -> dict:
    """`observe usage` / `usage_report`: one feature, or statistics by type (default), role or model."""
    if feature is not None and by is not None:
        raise ValueError("use either feature or by, not both")
    if by not in (None, "type", "role", "model"):
        raise ValueError("by must be one of type, role, model")
    _since(since)
    context = projects.resolve(root)
    if feature is not None:
        return feature_usage(context, feature, since)
    if by in (None, "type"):
        return type_stats(context, since, include_incomplete)
    return group_stats(context, by, since)


def mcp_report(root: str, feature: str | None = None, by: str | None = None, since: str | None = None,
               include_incomplete: bool = False) -> dict:
    try:
        return report(root, feature, by, since, include_incomplete)
    except (ValueError, FileNotFoundError, store.StoreError) as exc:
        return {"error": str(exc)}
