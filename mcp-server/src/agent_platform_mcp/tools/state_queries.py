"""Usage queries, explicit snapshot export/import and bounded retention."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from agent_platform_mcp import events
from agent_platform_mcp.tools import pricing, projects, store
from agent_platform_mcp.tools import recovery


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
        return {"schema": 3, "recovery": recovery.export_rows(db),
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
    if not isinstance(data, dict) or data.get("schema") not in (1, 2, 3):
        raise ValueError("unsupported observation export")
    expected = {"schema", "events", "usage", "reviews"} | ({"evidence"} if data["schema"] >= 2 else set()) | ({"recovery"} if data["schema"] >= 3 else set())
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
        pinned.update(row[0] for row in db.connection.execute("SELECT run_id FROM run_control WHERE state NOT IN ('completed','cancelled')"))
        candidates = db.connection.execute("SELECT run_id FROM runs WHERE ended_at IS NOT NULL AND ended_at<?", (boundary,)).fetchall()
        removed = 0
        for row in candidates:
            if row[0] not in pinned:
                db.connection.execute("DELETE FROM runs WHERE run_id=?", (row[0],))
                removed += 1
        return {"removed_runs": removed, "before": boundary, "review_history_retained": True,
                "active_runs_retained": True}
