"""Usage queries, explicit snapshot export/import and bounded retention."""

import json
import re
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from agent_platform_mcp import events
from agent_platform_mcp.tools import observation, pricing, projects, store
from agent_platform_mcp.tools import recovery
from agent_platform_mcp.tools import actions
from agent_platform_mcp.tools import continuation


def usage_summary(project_id: str | None = None, since: str | None = None,
                  scenario: dict | None = None) -> dict:
    with store.open() as db:
        runs = db.runs(project_id, since)
        totals = {key: [] for key in pricing.COUNTS}
        missing = 0
        missing_cost = 0
        costs = {}
        snapshots = []
        for run in runs:
            row = db.connection.execute("SELECT payload_json FROM usage WHERE run_id=?", (run["run_id"],)).fetchone()
            usage = json.loads(row[0]) if row else None
            if usage is None or usage["completeness"] != "full":
                missing += 1
            for key in totals:
                if usage and usage.get(key) is not None:
                    totals[key].append(usage[key])
            price = pricing.snapshot(scenario, run["model"]) if scenario is not None else run["payload"].get("price_snapshot")
            value = pricing.estimate(usage, price)
            if price and price not in snapshots:
                snapshots.append(price)
            if value is None:
                missing_cost += 1
            else:
                currency = price["currency"]
                costs[currency] = costs.get(currency, Decimal(0)) + value
        return {"runs": len(runs), "tokens": {key: sum(values) if values else None for key, values in totals.items()},
                "missing_runs": missing, "missing_fields": {key: len(runs) - len(values) for key, values in totals.items()},
                "cost": {"estimated": str(next(iter(costs.values()))) if len(costs) == 1 and not missing_cost else None,
                         "known_by_currency": {key: str(value) for key, value in costs.items()}, "reported": None,
                         "missing_runs": missing_cost, "snapshots": snapshots,
                         "scenario": "recalculated" if scenario is not None else "recorded_snapshot"}}


def export_snapshot() -> dict:
    with store.open() as db, db.connection:
        db.connection.execute("BEGIN")
        return {"schema": 5, "recovery": recovery.export_rows(db),
                "continuations": [dict(row) for row in db.connection.execute("SELECT * FROM continuations ORDER BY rowid")],
                "actions": [dict(row) for row in db.connection.execute("SELECT * FROM actions ORDER BY rowid")],
                "evidence": [dict(row) for row in db.connection.execute("SELECT * FROM evidence ORDER BY rowid")],
                "events": [json.loads(row[0]) for row in db.connection.execute("SELECT event_json FROM events ORDER BY rowid")],
                "usage": [{"run_id": row[0], "usage": json.loads(row[1])} for row in db.connection.execute("SELECT * FROM usage")],
                "reviews": [{"project_id": row[0], "task_id": row[1], "review": json.loads(row[2])}
                            for row in db.connection.execute("SELECT project_id,task_id,payload_json FROM review_results ORDER BY rowid")]}


def export_file(path: str) -> dict:
    destination = Path(path).absolute()
    projects._safe_storage(destination)
    if destination.suffix != ".json":
        raise ValueError("export requires a new .json file")
    data = export_snapshot()
    with destination.open("x", encoding="utf-8") as output:
        destination.chmod(0o600)
        json.dump(data, output, indent=2)
        output.write("\n")
    return {"path": str(destination), "runs": sum(event["event_type"] == "run_started" for event in data["events"])}


def import_snapshot(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("schema") not in (1, 2, 3, 4, 5):
        raise ValueError("unsupported observation export")
    expected = {"schema", "events", "usage", "reviews"} | ({"evidence"} if data["schema"] >= 2 else set()) | ({"recovery"} if data["schema"] >= 3 else set())
    if data["schema"] >= 4:
        expected.add("actions")
    if data["schema"] >= 5:
        expected.add("continuations")
    if set(data) != expected:
        raise ValueError("unsupported observation export")
    imported = 0
    with store.open() as db:
        # Replays are idempotent. A stopped import can be retried with the same IDs.
        for value in data["events"]:
            if value["event_type"] == "run_started":
                imported += db.record_event(events.RunEvent(**value))
        for value in data["reviews"]:
            db.record_review(events.ReviewResult(**value["review"]), value["project_id"], value["task_id"])
        for value in data["events"]:
            if value["event_type"] != "run_started":
                imported += db.record_event(events.RunEvent(**value))
        for value in data["usage"]:
            db.record_usage(value["run_id"], events.Usage(**value["usage"]))
        with db.connection:
            fields = ("id", "project_id", "task_id", "workspace", "ac_id", "verify_run_id", "profile_id", "status", "code_fingerprint", "criteria_hash", "ts", "profile_hash")
            for value in data.get("evidence", []):
                if set(value) != set(fields) or value["status"] not in {"passed", "failed", "error", "not_run", "stale"}:
                    raise ValueError("invalid evidence export row")
                previous = db.connection.execute("SELECT * FROM evidence WHERE id=?", (value["id"],)).fetchone()
                if previous:
                    if dict(previous) != value:
                        raise ValueError("conflicting imported evidence id")
                else:
                    db.connection.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", tuple(value[key] for key in fields))
            if data["schema"] >= 3:
                recovery.import_rows(db, data["recovery"])
            if data["schema"] >= 4:
                actions.import_rows(db, data["actions"])
            if data["schema"] >= 5:
                continuation.import_rows(db, data["continuations"])
    return {"imported_events": imported}


def import_file(path: str) -> dict:
    source = Path(path).absolute()
    projects._safe_storage(source)
    if source.suffix != ".json" or any(word in source.name.lower() for word in ("secret", "credential", ".env", ".pem", ".key")):
        raise ValueError("import requires an explicit non-secret .json export")
    if source.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("observation import exceeds 32 MiB")
    return import_snapshot(json.loads(source.read_text()))


def prune(before: str | None = None, retention_days: int = 180) -> dict:
    if type(retention_days) is not int or retention_days < 1:
        raise ValueError("retention_days must be a positive integer")
    boundary = store._timestamp(before) if before else (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    removed = batches = 0
    after = ""  # run_id keyset: a pinned run stays a candidate, so each batch starts past the previous one
    with store.open() as db:
        while True:
            # One write transaction per batch (DBA F-14): a large first prune never holds the write lock for
            # longer than a concurrent hook waits (5 s). The pins are re-read inside each batch's transaction.
            with db.connection:
                db.connection.execute("BEGIN IMMEDIATE")
                candidates = [row[0] for row in db.connection.execute(
                    "SELECT run_id FROM runs WHERE run_id>? AND ended_at IS NOT NULL AND ended_at<? ORDER BY run_id LIMIT ?",
                    (after, boundary, PRUNE_BATCH))]
                if not candidates:
                    break
                batches += 1
                pinned = _pinned(db)
                for run_id in candidates:
                    if run_id not in pinned:
                        db.connection.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
                        removed += 1
                after = candidates[-1]
            if len(candidates) < PRUNE_BATCH:
                break
    return {"removed_runs": removed, "before": boundary, "review_history_retained": True,
            "active_runs_retained": True, "batches": batches}


PRUNE_BATCH = 5000  # runs per prune write transaction: about 0.5 s on a 1M-event DB (DBA F-14: 50k runs took 5.4 s)


def _pinned(db) -> set:
    # Review history is retained to preserve unresolved role counters and audit IDs.
    pinned = {json.loads(row[0])["run_id"] for row in db.connection.execute("SELECT payload_json FROM review_results")}
    pinned.update(row[0] for row in db.connection.execute("SELECT verify_run_id FROM evidence"))
    pinned.update(row[0] for row in db.connection.execute("SELECT run_id FROM checkpoints"))
    pinned.update(row[0] for row in db.connection.execute("SELECT run_id FROM actions"))
    for row in db.connection.execute("SELECT parent_run_id,child_run_id FROM continuations"):
        pinned.update(row)
    pinned.update(row[0] for row in db.connection.execute("SELECT run_id FROM run_control WHERE state NOT IN ('completed','cancelled')"))
    return pinned


RESUMABLE = {"waiting", "failed", "interrupted"}  # continuation.claim takes these; prune keeps them too
# Only this run's index entries: the run_ended rows close-stale wrote for other runs are never re-read (DBA F-13).
NEWER = "SELECT max(ts) FROM events INDEXED BY events_run WHERE run_id=? AND rowid>?"
# The same read without the hint, for a DB that lost the index in this session (DBA F-15, REVIEW N-19): slower, never failing.
NEWER_UNINDEXED = "SELECT max(ts) FROM events WHERE run_id=? AND rowid>?"


def close_stale(older_than: str = "7d", dry_run: bool = False) -> dict:
    """Ends stale open LLM runs (claude/codex/unknown: the `stale_open_runs` population, DBA F-11, REVIEW N-12) as
    `abandoned`, at the run's last known activity (start, heartbeat or event), never at now (DBA F-9). A run whose
    recovery state is already `completed` lost only its `state end` and is ended `completed` (REVIEW N-13).
    Human-run only; writes only state.db. Skipped with a reason: a resumable recovery state or a checkpoint, as
    prune keeps them (REVIEW N-9), a live recorded process, activity within `older_than` (a run without a
    run_control row needs no event in that window, REVIEW N-11), and a run ended meanwhile. Each run is re-checked
    and closed in its own write transaction; a closed run also gets a `cancelled` run_control row (REVIEW N-10).
    A state.db error (lock timeout, integrity) stops the command with the runs closed so far (REVIEW N-15)."""
    match = re.fullmatch(r"([1-9][0-9]{0,3})([dh])", older_than or "")
    span = (timedelta(days=int(match[1])) if match[2] == "d" else timedelta(hours=int(match[1]))) if match else None
    if span is None or span < timedelta(days=1):
        raise ValueError("older_than must be at least one day, like 7d or 48h")
    boundary = (datetime.now(timezone.utc) - span).isoformat()
    from agent_platform_mcp.tools import usage_attribution
    stopped = None
    with store.open() as db:
        mark = db.connection.execute("SELECT coalesce(max(rowid),0) FROM events").fetchone()[0]
        indexed = db.connection.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='events_run'").fetchone()
        newer_sql = NEWER if indexed else NEWER_UNINDEXED
        rows = db.connection.execute(
            "SELECT r.run_id,r.event_json,r.started_at,e.last FROM runs r LEFT JOIN (SELECT run_id,max(ts) AS last FROM events "
            "WHERE run_id IN (SELECT run_id FROM runs WHERE ended_at IS NULL) GROUP BY run_id) e ON e.run_id=r.run_id "
            f"WHERE r.ended_at IS NULL AND r.started_at<? AND {usage_attribution.LLM_RUNS} ORDER BY r.started_at",
            (boundary, *usage_attribution.LLM_BACKENDS)).fetchall()
        listed = []
        for row in rows:
            item = {"run_id": row["run_id"], "started_at": row["started_at"]}
            try:
                with db.connection:
                    if not dry_run:
                        db.connection.execute("BEGIN IMMEDIATE")
                    item = _stale_item(db, row, boundary, mark, newer_sql)
                    if item["action"] == "close" and not dry_run:
                        _close(db, item)
            except sqlite3.Error as exc:  # the transaction rolled back; the runs closed before it stay closed
                stopped = f"storage error: {type(exc).__name__}"
                listed.append({**item, "action": "skip", "outcome": None, "reason": stopped})
                break
            except (KeyError, TypeError, ValueError) as exc:  # one unreadable run never stops the rest
                item = {**item, "action": "skip", "outcome": None, "reason": f"invalid run: {type(exc).__name__}"}
            listed.append(item)
    closing = [item["run_id"] for item in listed if item["action"] == "close"]
    reasons = {}
    for item in listed:
        if item["reason"]:
            reasons[item["reason"]] = reasons.get(item["reason"], 0) + 1
    return {"before": boundary, "stale_runs": len(rows), "run_ids": closing, "runs": listed, "skipped": reasons,
            "kept_live": reasons.get("live process", 0) + reasons.get("recent activity", 0),
            "closed": 0 if dry_run else len(closing), "dry_run": dry_run,
            "stopped": stopped, "unprocessed": len(rows) - len(listed)}


def _stale_item(db, row, boundary: str, mark: int, newer_sql: str = NEWER) -> dict:
    """The close-or-skip decision for one candidate, read inside its write transaction."""
    run_id, event = row["run_id"], json.loads(row["event_json"])
    ended = db.connection.execute("SELECT ended_at FROM runs WHERE run_id=?", (run_id,)).fetchone()
    control = db.connection.execute("SELECT state,heartbeat_at,pid,host FROM run_control WHERE run_id=?", (run_id,)).fetchone()
    newer = db.connection.execute(newer_sql, (run_id, mark)).fetchone()[0]
    times = [row["started_at"], row["last"], newer, store._timestamp(control["heartbeat_at"]) if control else None]
    last = max(value for value in times if value)
    item = {"run_id": run_id, "role": event.get("role"), "backend": event.get("backend"), "started_at": row["started_at"],
            "last_activity": last, "recovery_state": control["state"] if control else "none", "action": "skip",
            "outcome": None, "reason": None}
    if ended is None or ended[0]:
        item["reason"] = "already ended"
    elif control and control["state"] in RESUMABLE:
        item["reason"] = "resumable"
    elif db.connection.execute("SELECT 1 FROM checkpoints WHERE run_id=? LIMIT 1", (run_id,)).fetchone():
        item["reason"] = "checkpoint"
    elif control and recovery._alive(dict(control)):
        item["reason"] = "live process"
    elif last >= boundary or newer:
        item["reason"] = "recent activity"
    else:
        item["action"] = "close"
        item["outcome"] = "completed" if control and control["state"] == "completed" else "abandoned"
    return item


def _close(db, item: dict) -> None:
    # This reason lands in the run_ended event; run_control keeps a `completed` run's own reason (REVIEW N-17).
    if item["outcome"] == "completed":  # transition(completed) was recorded; only `state end` is missing
        reason = "state end recorded by state close-stale"
    else:
        reason = "open run closed by state close-stale"
    event = observation._derived(db.run(item["run_id"]), "run_ended", {"outcome": item["outcome"], "reason": reason})
    db.apply_event(replace(event, ts=item["last_activity"]))
    db.connection.execute("INSERT INTO run_control VALUES(?,?,?,?,?,?) ON CONFLICT(run_id) DO NOTHING",
                          (item["run_id"], "cancelled", item["last_activity"], None, None, reason))
