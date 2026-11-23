"""Usage queries, explicit snapshot export/import and bounded retention."""

import json
import re
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
    with store.open() as db, db.connection:
        db.connection.execute("BEGIN IMMEDIATE")
        # Review history is retained to preserve unresolved role counters and audit IDs.
        pinned = {json.loads(row[0])["run_id"] for row in db.connection.execute("SELECT payload_json FROM review_results")}
        pinned.update(row[0] for row in db.connection.execute("SELECT verify_run_id FROM evidence"))
        pinned.update(row[0] for row in db.connection.execute("SELECT run_id FROM checkpoints"))
        pinned.update(row[0] for row in db.connection.execute("SELECT run_id FROM actions"))
        for row in db.connection.execute("SELECT parent_run_id,child_run_id FROM continuations"):
            pinned.update(row)
        pinned.update(row[0] for row in db.connection.execute("SELECT run_id FROM run_control WHERE state NOT IN ('completed','cancelled')"))
        candidates = db.connection.execute("SELECT run_id FROM runs WHERE ended_at IS NOT NULL AND ended_at<?", (boundary,)).fetchall()
        removed = 0
        for row in candidates:
            if row[0] not in pinned:
                db.connection.execute("DELETE FROM runs WHERE run_id=?", (row[0],))
                removed += 1
        return {"removed_runs": removed, "before": boundary, "review_history_retained": True,
                "active_runs_retained": True}


RESUMABLE = {"waiting", "failed", "interrupted"}  # continuation.claim takes these; prune keeps them too


def close_stale(older_than: str = "7d", dry_run: bool = False) -> dict:
    """Ends stale open LLM runs (claude/codex/unknown: the `stale_open_runs` population, DBA F-11, REVIEW N-12) as
    `abandoned`, at the run's last known activity (start, heartbeat or event), never at now (DBA F-9). Human-run
    only; writes only state.db. Skipped with a reason: a resumable recovery state or a checkpoint, as prune keeps
    them (REVIEW N-9), a live recorded process, activity within `older_than` (a run without a run_control row
    needs no event in that window, REVIEW N-11), and a run ended meanwhile. Each run is re-checked and closed in
    its own write transaction; a closed run also gets a `cancelled` run_control row (REVIEW N-10)."""
    match = re.fullmatch(r"([1-9][0-9]{0,3})([dh])", older_than or "")
    span = (timedelta(days=int(match[1])) if match[2] == "d" else timedelta(hours=int(match[1]))) if match else None
    if span is None or span < timedelta(days=1):
        raise ValueError("older_than must be at least one day, like 7d or 48h")
    boundary = (datetime.now(timezone.utc) - span).isoformat()
    from agent_platform_mcp.tools import usage_attribution
    with store.open() as db:
        mark = db.connection.execute("SELECT coalesce(max(rowid),0) FROM events").fetchone()[0]
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
                    item = _stale_item(db, row, boundary, mark)
                    if item["action"] == "close" and not dry_run:
                        _abandon(db, item)
            except (KeyError, TypeError, ValueError) as exc:  # one unreadable run never stops the rest
                item = {**item, "action": "skip", "reason": f"invalid run: {type(exc).__name__}"}
            listed.append(item)
    closing = [item["run_id"] for item in listed if item["action"] == "close"]
    reasons = {}
    for item in listed:
        if item["reason"]:
            reasons[item["reason"]] = reasons.get(item["reason"], 0) + 1
    return {"before": boundary, "stale_runs": len(listed), "run_ids": closing, "runs": listed, "skipped": reasons,
            "kept_live": reasons.get("live process", 0) + reasons.get("recent activity", 0),
            "closed": 0 if dry_run else len(closing), "dry_run": dry_run}


def _stale_item(db, row, boundary: str, mark: int) -> dict:
    """The close-or-skip decision for one candidate, read inside its write transaction."""
    run_id, event = row["run_id"], json.loads(row["event_json"])
    ended = db.connection.execute("SELECT ended_at FROM runs WHERE run_id=?", (run_id,)).fetchone()
    control = db.connection.execute("SELECT state,heartbeat_at,pid,host FROM run_control WHERE run_id=?", (run_id,)).fetchone()
    newer = db.connection.execute("SELECT max(ts) FROM events WHERE rowid>? AND run_id=?", (mark, run_id)).fetchone()[0]
    times = [row["started_at"], row["last"], newer, store._timestamp(control["heartbeat_at"]) if control else None]
    last = max(value for value in times if value)
    item = {"run_id": run_id, "role": event.get("role"), "backend": event.get("backend"), "started_at": row["started_at"],
            "last_activity": last, "recovery_state": control["state"] if control else "none", "action": "skip", "reason": None}
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
    return item


def _abandon(db, item: dict) -> None:
    reason = "open run closed by state close-stale"
    event = observation._derived(db.run(item["run_id"]), "run_ended", {"outcome": "abandoned", "reason": reason})
    db.apply_event(replace(event, ts=item["last_activity"]))
    db.connection.execute("INSERT INTO run_control VALUES(?,?,?,?,?,?) ON CONFLICT(run_id) DO NOTHING",
                          (item["run_id"], "cancelled", item["last_activity"], None, None, reason))
