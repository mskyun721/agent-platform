"""Opt-out collectors and explicit direct-session lifecycle APIs."""

from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from agent_platform_mcp import config, events
from agent_platform_mcp.tools import pricing, projects, skills, store

_current: ContextVar[dict | None] = ContextVar("platform_observation", default=None)


def process_heartbeat(pid: int):
    current = _current.get()
    if current and current["observability"].get("stored"):
        try:
            from agent_platform_mcp.tools import recovery
            recovery.heartbeat(current["run_id"], pid)
        except Exception as exc:
            current["observability"]["heartbeat_error"] = type(exc).__name__


def native_usage(usage: events.Usage) -> None:
    observation = _current.get()
    if observation is None or not observation["observability"]["stored"]:
        return
    try:
        with store.open() as db:
            db.record_usage(observation["run_id"], usage)
        observation["observability"]["usage"] = usage.completeness
    except Exception as exc:
        observation["observability"]["usage_error"] = type(exc).__name__


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enabled() -> bool:
    return config.agent_config().get("observability", {}).get("enabled", True) is not False


def _failure(exc: Exception) -> dict:
    return {"stored": False, "error": type(exc).__name__}


def start_context(task_id: str, role: str, backend: str | None, context: projects.ProjectContext,
                  model: str | None = None, source: str = "direct") -> dict:
    from agent_platform_mcp.tools.feature import canonical_feature

    task_id = canonical_feature(task_id)
    if role not in events.ROLES:
        raise ValueError("unknown role")
    run_id = str(uuid4())
    result = {"run_id": run_id, "project_id": context.project_id}
    try:
        if not _enabled():
            return {**result, "observability": {"stored": False, "reason": "disabled"}}
        snapshot = {"skill_versions": {}, "skill_versions_source": "expected"}
        if context.project_id and backend in skills.NATIVE:
            snapshot = skills.active_versions(context.project_id, backend, context.path)
        price = pricing.snapshot(config.agent_config().get("pricing"), model)
        event = events.RunEvent(str(uuid4()), run_id, None, context.project_id, task_id, role,
                                "run_started", _now(), backend, model, snapshot["skill_versions"],
                                {"workspace": str(context.path), "skill_versions_source": snapshot["skill_versions_source"],
                                 "price_snapshot": price},
                                source, "partial")
        with store.open() as db:
            db.record_event(event)
            db.record_usage(run_id, events.Usage(None, None, None, None, "unavailable", "unavailable"))
        return {**result, "observability": {"stored": True, "usage": "unavailable", "skill_versions_source": "expected"}}
    except Exception as exc:
        return {**result, "observability": _failure(exc)}


def run_start(task_id: str, role: str, backend: str | None = None, model: str | None = None,
              root: str | None = None) -> dict:
    return start_context(task_id, role, backend, projects.resolve(root), model)


def _derived(run: dict, event_type: str, payload: dict) -> events.RunEvent:
    values = {key: run[key] for key in events.RunEvent.__dataclass_fields__}
    return replace(events.RunEvent(**values), event_id=str(uuid4()), event_type=event_type, ts=_now(), payload=payload)


def run_end(run_id: str, outcome: str, reason: str | None = None, duration_sec: float | None = None) -> dict:
    if outcome not in {"completed", "failed", "interrupted", "cancelled"}:
        raise ValueError("invalid run outcome")
    try:
        if not _enabled():
            return {"run_id": run_id, "observability": {"stored": False, "reason": "disabled"}}
        with store.open() as db:
            payload = {"outcome": outcome}
            if reason is not None:
                payload["reason"] = reason
            if duration_sec is not None:
                payload["duration_sec"] = duration_sec
            db.record_event(_derived(db.run(run_id), "run_ended", payload))
        return {"run_id": run_id, "observability": {"stored": True}}
    except Exception as exc:
        return {"run_id": run_id, "observability": _failure(exc)}


def observed(context: projects.ProjectContext, task_id: str, role: str, backend: str,
             dry_run: bool, action, model: str | None = None) -> dict:
    if dry_run:
        return action()
    observation = start_context(task_id, role, backend, context, model, "wrapper")
    token = _current.set(observation)
    started = time.monotonic()
    try:
        result = action()
    except BaseException as exc:
        if observation["observability"]["stored"]:
            run_end(observation["run_id"], "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) or getattr(exc, "interrupted", False) else "failed",
                    "execution_error", round(time.monotonic() - started, 3))
        raise
    finally:
        _current.reset(token)
    if observation["observability"]["stored"]:
        end = run_end(observation["run_id"], "completed" if result.get("exit_code") == 0 else "failed",
                      duration_sec=round(time.monotonic() - started, 3))
        if not end["observability"]["stored"]:
            observation = end
    return {**result, **observation}


def point(result: dict, project: projects.ProjectContext, role: str, event_type: str, payload: dict) -> dict:
    observation = start_context(result.get("feature", "verification"), role, None, project)
    if observation["observability"]["stored"]:
        try:
            with store.open() as db:
                db.record_event(_derived(db.run(observation["run_id"]), event_type, payload))
            end = run_end(observation["run_id"], "completed" if result.get("passed") else "failed")
            if not end["observability"]["stored"]:
                observation = end
        except Exception as exc:
            observation["observability"] = _failure(exc)
    return observation


def review_result_record(task_id: str, role: str, decision: str, artifact: str, code_fingerprint: str,
                         reviewer_id: str, decision_id: str, root: str | None = None, run_id: str | None = None) -> dict:
    from agent_platform_mcp.tools.feature import canonical_feature

    context = projects.resolve(root)
    if context.project_id is None:
        raise ValueError("register the project before recording review decisions")
    task_id = canonical_feature(task_id)
    with store.open() as db:
        # Allocation and insertion share one writer transaction; retries use the caller's decision ID.
        with db.connection:
            db.connection.execute("BEGIN IMMEDIATE")
            previous = db.connection.execute("SELECT * FROM review_results WHERE decision_id=?", (decision_id,)).fetchone()
            if previous:
                import json
                result = events.ReviewResult(**json.loads(previous["payload_json"]))
                proposed = replace(result, role=role, decision=decision, artifact=artifact, code_fingerprint=code_fingerprint,
                                   reviewer_id=reviewer_id, run_id=run_id)
            else:
                row = db.connection.execute("SELECT review_cycle_id FROM review_results WHERE project_id IS ? AND task_id=? ORDER BY rowid DESC LIMIT 1",
                                            (context.project_id, task_id)).fetchone()
                cycle = row[0] if row else str(uuid4())
                attempt = db.connection.execute("SELECT COALESCE(MAX(attempt),0)+1 FROM review_results WHERE review_cycle_id=? AND role=?", (cycle, role)).fetchone()[0]
                proposed = events.ReviewResult(decision_id, cycle, str(uuid4()), reviewer_id, role, attempt, decision,
                                              code_fingerprint, run_id, artifact)
            if run_id:
                run = db.run(run_id)
                if (run["project_id"], run["task_id"], run["role"]) != (context.project_id, task_id, role):
                    raise ValueError("review context differs from run")
            inserted = db._review(proposed, context.project_id, task_id, _now())
        return {"decision_id": decision_id, "review_cycle_id": proposed.review_cycle_id,
                "attempt": proposed.attempt, "stored": True, "inserted": inserted}
