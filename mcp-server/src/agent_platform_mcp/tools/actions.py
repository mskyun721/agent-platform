"""Explicitly confirmed external-action ledger; uncertain writes are never replayed."""

import json
from uuid import uuid4

from agent_platform_mcp.tools import recovery, store

SCHEMA = """
CREATE TABLE actions (
 action_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
 kind TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL,
 ts TEXT NOT NULL, target_json TEXT NOT NULL, confirmed_by TEXT, ref TEXT);
"""
KINDS = {"push", "pr", "deploy", "confluence_page"}
STATES = {"planned", "confirmed", "executing", "executed", "skipped_duplicate", "failed", "uncertain"}


def _get(db, action_id):
    row = db.connection.execute("SELECT * FROM actions WHERE action_id=?", (action_id,)).fetchone()
    if row is None:
        raise ValueError("unknown external action")
    return dict(row)


def list_actions(run_id=None):
    with store.open() as db:
        return [dict(row) for row in db.connection.execute("SELECT * FROM actions WHERE (? IS NULL OR run_id=?) ORDER BY rowid", (run_id, run_id))]


def plan(run_id: str, kind: str, key: str, target: dict):
    if kind not in KINDS or not isinstance(target, dict) or not target:
        raise ValueError("known action kind and structured target required")
    recovery._text(key)
    encoded = json.dumps(target, sort_keys=True, allow_nan=False)
    if len(encoded) > 8192:
        raise ValueError("external target metadata exceeds limit")
    recovery.metadata(target)
    with store.open() as db, db.connection:
        db.connection.execute("BEGIN IMMEDIATE")
        run = db.run(run_id)
        recovery._workspace(run)
        previous = db.connection.execute("SELECT * FROM actions WHERE idempotency_key=?", (key,)).fetchone()
        if previous:
            original = db.run(previous["run_id"])
            same_context = all(original[field] == run[field] for field in ("project_id", "task_id")) and original["payload"]["workspace"] == run["payload"]["workspace"]
            if not same_context or previous["kind"] != kind or previous["target_json"] != encoded:
                raise ValueError("idempotency key reused for another action or target")
            return dict(previous)
        value = {"action_id": str(uuid4()), "run_id": run_id, "kind": kind, "idempotency_key": key,
                 "status": "planned", "ts": recovery.now(), "target_json": encoded, "confirmed_by": None, "ref": None}
        db.connection.execute("INSERT INTO actions VALUES(:action_id,:run_id,:kind,:idempotency_key,:status,:ts,:target_json,:confirmed_by,:ref)", value)
        return value


def confirm(action_id: str, confirmed_by: str):
    recovery._text(confirmed_by)
    with store.open() as db, db.connection:
        db.connection.execute("BEGIN IMMEDIATE")
        value = _get(db, action_id)
        if value["status"] not in {"planned", "confirmed", "failed"}:
            raise ValueError("action cannot be confirmed for replay")
        db.connection.execute("UPDATE actions SET status='confirmed',confirmed_by=?,ts=? WHERE action_id=?",
                              (confirmed_by, recovery.now(), action_id))
        return _get(db, action_id)


def execute(action_id: str, adapter):
    # Claim before remote lookup so concurrent callers cannot both write remotely.
    with store.open() as db, db.connection:
        db.connection.execute("BEGIN IMMEDIATE")
        value = _get(db, action_id)
        if value["status"] in {"executed", "skipped_duplicate"}:
            return {**value, "status": "skipped_duplicate"}
        if value["status"] in {"executing", "uncertain"}:
            return {**value, "status": "uncertain", "reason": "inspect remote state; never blindly replay"}
        if value["status"] != "confirmed":
            raise ValueError("explicit user confirmation required")
        recovery._workspace(db.run(value["run_id"]))
        db.connection.execute("UPDATE actions SET status='executing',ts=? WHERE action_id=?", (recovery.now(), action_id))
    attempted = False
    try:
        existing = adapter.lookup(value)
        if existing is not None:
            recovery._text(existing)
            status, reference = "skipped_duplicate", existing
        else:
            attempted = True
            reference = adapter.execute(value)
            recovery._text(reference)
            status = "executed"
    except BaseException:
        status, reference = ("uncertain" if attempted else "failed"), None
        with store.open() as db, db.connection:
            db.connection.execute("UPDATE actions SET status=?,ts=? WHERE action_id=?", (status, recovery.now(), action_id))
        raise
    with store.open() as db, db.connection:
        db.connection.execute("UPDATE actions SET status=?,ref=?,ts=? WHERE action_id=?", (status, reference, recovery.now(), action_id))
        return _get(db, action_id)


def reconcile(action_id: str, adapter):
    with store.open() as db:
        value = _get(db, action_id)
        if value["status"] not in {"uncertain", "executing"}:
            raise ValueError("only uncertain or interrupted in-flight actions need reconciliation")
        recovery._workspace(db.run(value["run_id"]))
    existing = adapter.lookup(value)
    if existing is None:
        return {**value, "status": "uncertain", "reason": "remote completion unverified; manual inspection required"}
    recovery._text(existing)
    with store.open() as db, db.connection:
        db.connection.execute("UPDATE actions SET status='skipped_duplicate',ref=?,ts=? WHERE action_id=? AND status IN ('uncertain','executing')",
                              (existing, recovery.now(), action_id))
        return _get(db, action_id)


def import_rows(db, rows):
    fields = ("action_id", "run_id", "kind", "idempotency_key", "status", "ts", "target_json", "confirmed_by", "ref")
    for value in rows:
        if set(value) != set(fields) or value["kind"] not in KINDS or value["status"] not in STATES:
            raise ValueError("invalid action export")
        recovery.metadata(value)
        store._timestamp(value["ts"])
        db.run(value["run_id"])
        previous = db.connection.execute("SELECT * FROM actions WHERE action_id=?", (value["action_id"],)).fetchone()
        if previous and dict(previous) != value:
            raise ValueError("conflicting action snapshot; never overwrite live ledger")
        if not previous:
            db.connection.execute("INSERT INTO actions VALUES(?,?,?,?,?,?,?,?,?)", tuple(value[field] for field in fields))
