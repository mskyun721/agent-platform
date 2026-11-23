"""Per-feature token usage, per-type/role statistics and advisory budgets.

Read-only (`mode=ro`) over the existing runs/usage/review_results/events tables and the
feature's docs front-matter. Results carry counts and identifiers only (BR-8). Backends are never
summed together (A-4) and unmeasured usage is never filled with zero (BR-5).
"""

from __future__ import annotations

import contextlib
import json
import statistics
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from agent_platform_mcp import config, events, frontmatter
from agent_platform_mcp.tools import pricing, projects, store, usage_attribution
from agent_platform_mcp.tools.feature import canonical_feature, safe_path
from agent_platform_mcp.tools.review_requests import review_request_rows

TYPES = ("work", "light", "full")
COUNTS = pricing.COUNTS
MIN_SAMPLE = 3
REVIEW_ROLES = ("reviewer", "security", "dba", "qa")
GATE_ROLES = ("backend", "reviewer", "security", "dba", "qa", "cicd")
UNKNOWN = "unknown"
MAX_DOC_BYTES = 1024 * 1024
LIMITATIONS = [
    "Only runs recorded with the feature key as task_id are counted; earlier work has no usage records (A-5).",
    "Usage with completeness != full is excluded from sums and counted as missing; it is never zero-filled.",
    "Backends define input/cache tokens differently; totals are per backend and a single total exists only for one backend.",
    "Handoff/verification point records are not LLM executions and are excluded from run counts.",
    "A collected session turn's usage goes to a direct run only when exactly one run of the same project and backend "
    "overlaps it; ambiguous_runs/unattributed_runs count the other turns and are null when nothing was collected.",
    "A run started outside a detectable host (backend unknown) takes the turns of the one session that overlaps it, "
    "even a concurrent session opened for other work in the same project.",
    "An attributed sum stays after its turns expire (7 days); it is recomputed only from retained turns when a newer "
    "turn overlaps the run again, so a run open across the expiry can shrink to its retained turns.",
    "Type/role token statistics use fully measured samples only (n = n_measured); a feature with any unmeasured run "
    "is counted as partially_measured and excluded, and its feature report keeps the known sum with complete: false.",
    "since filters runs only; quality sources cover all time, so a feature spanning the since date contributes a partial sum.",
    "human_interventions counts decided review-request rows in PRD/WORK/REVIEW.md plus repeated-rejection recommendations only.",
    "work items keep QA results in WORK.md, so their QA defects are unknown unless bugs/ exists.",
    "Docs larger than 1 MiB are treated as absent. A missing or non-current state.db reports no_data and is never created.",
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


def _text(path: Path) -> str | None:
    """File text up to MAX_DOC_BYTES; larger or absent files read as None."""
    if not path.is_file() or path.stat().st_size > MAX_DOC_BYTES:
        return None
    with path.open("rb") as stream:
        raw = stream.read(MAX_DOC_BYTES + 1)
    return None if len(raw) > MAX_DOC_BYTES else raw.decode("utf-8", errors="replace")


def _front(path: Path, project: Path) -> dict:
    safe_path(path, project)
    text = _text(path)
    return (frontmatter.parse(text) or {}) if text is not None else {}


def feature_kind(project: Path, key: str) -> dict:
    """Work type (gate_check's track rule, A-2) and completion (A-3) of one feature folder.

    completed: ready for release handoff, i.e. every cicd gate prerequisite of the track is
    approved (SECURITY-AUDIT.md too when the declared risk is high), or WORK/PRD front-matter
    has `archived: true`. A missing folder reports exists=False and type None."""
    name = canonical_feature(key)
    target = config.docs_dir(name, project_dir=project)
    safe_path(target, project)
    if not target.is_dir():
        return {"feature": display_key(name), "exists": False, "type": None, "completed": False}
    kind = "work" if (target / "WORK.md").is_file() else (
        "light" if name.startswith(config.LIGHT_TRACK_PREFIXES) else "full")
    anchors = {anchor: _front(target / anchor, project) for anchor in ("WORK.md", "PRD.md")}
    completed = any(str(front.get("archived", "")).lower() == "true" for front in anchors.values())
    if not completed:
        risk = anchors["WORK.md" if kind == "work" else "PRD.md"].get("risk")
        required = config.agent_prerequisites(kind, "cicd", risk)
        completed = all(_front(target / file, project).get("status") == "approved" for file in required)
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


def _runs(connection, context: projects.ProjectContext, since: str | None, task_id: str | None = None) -> list[dict]:
    """One joined scan (runs_project index); handoff/verification point runs are excluded."""
    rows = connection.execute(
        "SELECT r.run_id,r.task_id,r.event_json,u.payload_json FROM runs r LEFT JOIN usage u ON u.run_id=r.run_id "
        "WHERE r.project_id IS ? AND (? IS NULL OR r.started_at>=?) AND (? IS NULL OR r.task_id=?) "
        "AND r.run_id NOT IN (SELECT run_id FROM events WHERE event_type IN ('handoff','verification')) "
        "ORDER BY r.started_at,r.run_id", (context.project_id, since, since, task_id, task_id))
    result = []
    for run_id, task, event_json, usage_json in rows:
        event = json.loads(event_json)
        payload = event.get("payload") or {}
        if payload.get("point") or (context.project_id is None and payload.get("workspace") != str(context.path)):
            continue  # a marked point run stays excluded even if its point event failed (L-4)
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
    by_backend = {}
    for backend, items in by_backend_runs.items():
        missing = sum(run["usage"] is None for run in items)
        by_backend[backend] = {"runs": len(items), "missing": missing, "complete": missing == 0, "tokens": _tokens(items)}
    by_role = {}
    for role, items in by_role_runs.items():
        inputs = {backend: _tokens([run for run in items if run["backend"] == backend])["input_tokens"]
                  for backend in sorted({run["backend"] for run in items})}
        by_role[role] = {"runs": len(items), "reworks": len(items) - 1, "missing": sum(run["usage"] is None for run in items),
                         "input_tokens": next(iter(inputs.values())) if len(inputs) == 1 else None,
                         "input_tokens_by_backend": inputs}
    cost, missing_cost = _cost(runs)
    complete = bool(runs) and all(item["complete"] for item in by_backend.values())
    return {"runs": len(runs), "complete": complete, "by_backend": by_backend,
            "total": next(iter(by_backend.values()))["tokens"] if len(by_backend) == 1 else None,
            "by_role": by_role, "cost": cost, "missing_cost": missing_cost}


def _stats(values: list, digits: int = 0) -> dict | None:
    if not values:
        return None
    rounded = (lambda value: round(value)) if digits == 0 else (lambda value: round(value, digits))
    return {"n": len(values), "mean": rounded(statistics.fmean(values)), "median": rounded(statistics.median(values)), "max": max(values)}


def _quality_sources(connection, context: projects.ProjectContext, task_id: str | None = None) -> dict:
    """review_results and handoff records per task, each read in one scan (BR-9, BR-10)."""
    sources = defaultdict(lambda: {"reviews": [], "handoffs": []})
    for task, payload in connection.execute(
            "SELECT task_id,payload_json FROM review_results WHERE project_id IS ? AND (? IS NULL OR task_id=?) ORDER BY rowid",
            (context.project_id, task_id, task_id)):
        sources[task]["reviews"].append(json.loads(payload))
    for task, run_json, event_json in connection.execute(
            "SELECT r.task_id,r.event_json,e.event_json FROM events e JOIN runs r ON r.run_id=e.run_id "
            "WHERE e.event_type='handoff' AND r.project_id IS ? AND (? IS NULL OR r.task_id=?) ORDER BY e.ts,e.rowid",
            (context.project_id, task_id, task_id)):
        if context.project_id is None and (json.loads(run_json).get("payload") or {}).get("workspace") != str(context.path):
            continue
        sources[task]["handoffs"].append(json.loads(event_json)["payload"])
    return sources


def _bugs(target: Path, project: Path):
    """BUG-*.md severity front-matter; no bugs/ and no TEST-PLAN.md means QA left no record."""
    folder, plan = target / "bugs", target / "TEST-PLAN.md"
    safe_path(folder, project)
    safe_path(plan, project)
    if not folder.is_dir():
        return {"P0": 0, "P1": 0, "other": 0} if plan.is_file() else UNKNOWN
    counts = {"P0": 0, "P1": 0, "other": 0}
    for path in sorted(folder.glob("BUG-*.md")):
        severity = str(_front(path, project).get("severity", "")).strip().upper()
        counts[severity if severity in {"P0", "P1"} else "other"] += 1
    return counts


def _review_requests(target: Path, project: Path):
    found, decided = False, 0
    for file in ("PRD.md", "WORK.md", "REVIEW.md"):
        path = target / file
        safe_path(path, project)
        text = _text(path)
        if text is not None:
            found = True
            decided += sum(row["resolved"] for row in review_request_rows(text))
    return decided if found else UNKNOWN


def quality(context: projects.ProjectContext, name: str, sources: dict) -> dict:
    """Rejections/cycles, first-pass gates, QA bugs and human interventions; never a combined score."""
    reviews, handoffs = sources["reviews"], sources["handoffs"]
    rejections = {role: sum(row["decision"] == "rejected" for row in reviews if row["role"] == role)
                  if any(row["role"] == role for row in reviews) else UNKNOWN for role in REVIEW_ROLES}
    streaks, recommended = defaultdict(int), 0
    for row in reviews:  # one recommendation each time a role reaches 3 consecutive rejections (store.review_status)
        streaks[row["role"]] = streaks[row["role"]] + 1 if row["decision"] == "rejected" else 0
        recommended += streaks[row["role"]] == 3
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
            "human_interventions": requests if requests == UNKNOWN or not reviews else requests + recommended,
            "intervention_recommended": recommended if reviews else UNKNOWN}


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
        result[metric] = _stats(values, 2) or {"n": 0}
    gates = [value for row in rows for value in row["first_pass"]]
    result["first_pass_gates"] = {"n": len(gates), "passed": sum(gates)}
    return result


def budget_status(kind: str | None, result: dict, runs: list[dict], settings: dict | None = None,
                  budget: dict | None = None) -> dict:
    """BR-6: advisory input-token budget. over/within/unknown; never changes gate results."""
    status = {"status": UNKNOWN, "feature_input_tokens": None, "limit": None, "role_over": []}
    try:
        budget = budget if budget is not None else load_budget(settings)
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


@contextlib.contextmanager
def _reader():
    """Read-only state DB connection (or None and the reason); never creates or migrates."""
    connection, reason = store.open_readonly()
    try:
        yield connection, reason
    finally:
        if connection is not None:
            connection.close()


def _no_data(reason: str, **head) -> dict:
    return {**head, "status": "no_data", "reason": reason, "limitations": LIMITATIONS}


def gate_usage(context: projects.ProjectContext, name: str, track: str) -> dict:
    """gate/handoff `usage` key. Opens the state DB read-only and only when a budget is configured."""
    unknown = {"status": UNKNOWN, "feature_input_tokens": None, "limit": None, "role_over": []}
    try:
        budget = load_budget()
        if budget == {"types": {}, "roles": {}}:
            return budget_status(track, {"total": None, "by_backend": {}}, [], budget=budget)
        with _reader() as (db, reason):
            if db is None:
                return {**unknown, "reason": reason}
            runs = _runs(db, context, None, canonical_feature(name))
        return budget_status(track, aggregate(runs), runs, budget=budget)
    except ValueError as exc:
        return {**unknown, "reason": str(exc)}
    except Exception as exc:  # advisory only: never break a gate
        return {**unknown, "reason": type(exc).__name__}


def feature_usage(context: projects.ProjectContext, key: str, since: str | None = None) -> dict:
    name = canonical_feature(key)
    kind = feature_kind(context.path, name)
    head = {"feature": kind["feature"], "type": kind["type"], "completed": kind["completed"], "since": since}
    with _reader() as (db, reason):
        runs = _runs(db, context, _since(since), name) if db else []
        sources = _quality_sources(db, context, name)[name] if db else None
        attribution = usage_attribution.feature_counts(db, context, name, _since(since)) if db else None
    if not runs and not kind["exists"]:
        raise ValueError(f"no runs or docs for feature: {kind['feature']}")
    if db is None:
        return _no_data(reason, **head)
    result = aggregate(runs)
    return {**head, **result, "quality": quality(context, name, sources), **attribution,
            "budget": budget_status(kind["type"], result, runs), "limitations": LIMITATIONS}


def _grouped(db, context: projects.ProjectContext, since: str | None) -> dict:
    grouped = defaultdict(list)
    for run in _runs(db, context, _since(since)):
        grouped[run["task_id"]].append(run)
    return grouped


def _backend_entry(features: list[dict], backend: str) -> dict:
    """H-1/H-2: statistics over fully measured features only; n counts those samples."""
    used = [feature for feature in features if backend in feature["by_backend"]]
    measured = [feature["by_backend"][backend] for feature in used if feature["complete"]]
    entry = {"n": len(measured), "n_measured": len(measured), "n_total": len(used),
             "partially_measured": len(used) - len(measured),
             "missing_runs": sum(feature["by_backend"][backend]["missing"] for feature in used),
             **{key: _stats([item["tokens"][key] for item in measured if item["tokens"][key] is not None]) for key in COUNTS}}
    if len(measured) < MIN_SAMPLE:
        entry["status"] = "insufficient_sample"
    return entry


def type_stats(context: projects.ProjectContext, since: str | None = None, include_incomplete: bool = False) -> dict:
    """BR-4: completed, fully measured features only (unless include_incomplete); n<3 is insufficient_sample."""
    scope = "all features" if include_incomplete else "completed features only"
    samples = {kind: [] for kind in TYPES}
    qualities = {kind: [] for kind in TYPES}
    excluded = {"in_progress": 0, "no_docs": 0, "unsafe_path": 0}
    with _reader() as (db, reason):
        if db is None:
            return _no_data(reason, scope=scope, since=since)
        grouped, sources = _grouped(db, context, since), _quality_sources(db, context)
    for task, runs in grouped.items():
        try:
            canonical_feature(task)
        except ValueError:
            excluded["no_docs"] += 1
            continue
        try:  # a symlinked or escaping feature folder is skipped, not fatal (fail-closed per feature)
            kind = feature_kind(context.path, task)
            if not kind["exists"]:
                excluded["no_docs"] += 1
                continue
            if not kind["completed"] and not include_incomplete:
                excluded["in_progress"] += 1
                continue
            row = quality(context, task, sources[task])
        except ValueError:
            excluded["unsafe_path"] += 1
            continue
        result = aggregate(runs)
        samples[kind["type"]].append(result)
        qualities[kind["type"]].append(_quality_scalars(row, result))
    types = {kind: {backend: _backend_entry(features, backend)
                    for backend in sorted({backend for feature in features for backend in feature["by_backend"]})}
             if features else {"n": 0, "status": "no_data"} for kind, features in samples.items()}
    return {"scope": scope, "since": since, "types": types,
            "quality": {kind: _quality_stats(rows) for kind, rows in qualities.items() if rows},
            "partially_measured": sum(not feature["complete"] for features in samples.values() for feature in features),
            "in_progress_excluded": excluded["in_progress"], "no_docs_excluded": excluded["no_docs"],
            "unsafe_path_excluded": excluded["unsafe_path"], **usage_attribution.project_counts(context, _since(since)),
            "limitations": LIMITATIONS}


def group_stats(context: projects.ProjectContext, by: str = "role", since: str | None = None) -> dict:
    """Per-run statistics per role (or model) x backend, including in-progress features; n counts measured runs."""
    field = {"role": "role", "model": "model"}[by]
    with _reader() as (db, reason):
        if db is None:
            return _no_data(reason, scope="all runs", since=since)
        grouped = _grouped(db, context, since)
    groups = defaultdict(list)
    for runs in grouped.values():
        for run in runs:
            groups[(run[field], run["backend"])].append(run)
    result = defaultdict(dict)
    for (name, backend), runs in sorted(groups.items()):
        measured = [run["usage"] for run in runs if run["usage"]]
        entry = {"n": len(measured), "n_measured": len(measured), "n_total": len(runs), "missing_runs": len(runs) - len(measured),
                 **{key: _stats([usage[key] for usage in measured if usage.get(key) is not None]) for key in COUNTS}}
        if len(measured) < MIN_SAMPLE:
            entry["status"] = "insufficient_sample"
        result[name][backend] = entry
    return {"scope": "all runs", "since": since, f"{by}s": dict(result), **usage_attribution.project_counts(context, _since(since)),
            "limitations": LIMITATIONS}


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
    except Exception as exc:  # e.g. sqlite3.Error, KeyError from a corrupt record: type name only, no content
        return {"error": type(exc).__name__}
