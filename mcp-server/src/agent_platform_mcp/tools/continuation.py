"""Explicit fresh-session claims; preserve old attempt history and prevent duplicates."""

import json
import sqlite3
import socket

from agent_platform_mcp.tools import fingerprint, observation, projects, recovery, store

SCHEMA = """
CREATE TABLE continuations (
 parent_run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
 child_run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id));
"""


def claim(run_id: str, pid: int):
    if type(pid) is not int or pid < 1 or not recovery._alive({"pid": pid, "host": socket.gethostname()}):
        raise ValueError("continuation requires the new session's actual PID")
    with store.open() as db:
        row = db.connection.execute("SELECT child_run_id FROM continuations WHERE parent_run_id=?", (run_id,)).fetchone()
        if row:
            return {"run_id": row[0], "parent_run_id": run_id, "claimed": False, "reason": "already continued; inspect the child run", "auto_executed": False}
    inspected = recovery.resume(run_id)
    if inspected["verdict"] != "resumable":
        raise ValueError("only an unchanged resumable checkpoint can be claimed")
    with store.open() as db:
        previous = db.run(run_id)
        workspace = recovery._workspace(previous)
    started = observation.start_context(previous["task_id"], previous["role"], previous["backend"],
                                        projects.resolve(workspace), previous["model"], parent_run_id=run_id)
    if not started["observability"]["stored"]:
        raise RuntimeError("cannot persist continuation; no execution was launched")
    child_id = started["run_id"]
    try:
        with store.open() as db, db.connection:
            db.connection.execute("BEGIN IMMEDIATE")
            current = recovery._state(db, run_id)
            if current["state"] not in {"failed", "waiting", "interrupted"} or recovery._alive(current):
                raise ValueError("previous execution changed or is still active")
            snapshot = fingerprint.code_fingerprint(recovery._workspace(db.run(run_id)))
            if snapshot["fingerprint"] != inspected["checkpoint"]["snapshot"]["fingerprint"]:
                raise ValueError("workspace changed while claiming continuation")
            db.connection.execute("INSERT INTO continuations VALUES(?,?)", (run_id, child_id))
            value = {**inspected["checkpoint"], "run_id": child_id, "seq": 1, "ts": recovery.now(), "snapshot": snapshot}
            db.connection.execute("INSERT INTO checkpoints VALUES(?,?,?)", (child_id, 1, recovery.metadata(value)))
            control = recovery._state(db, child_id)
            control.update(pid=pid, host=socket.gethostname(), heartbeat_at=recovery.now())
            recovery._save(db, control)
    except sqlite3.IntegrityError:
        observation.run_end(child_id, "cancelled", "another continuation already claimed this checkpoint")
        with store.open() as db:
            row = db.connection.execute("SELECT child_run_id FROM continuations WHERE parent_run_id=?", (run_id,)).fetchone()
        if row is None:
            raise
        return {"run_id": row[0], "parent_run_id": run_id, "claimed": False, "auto_executed": False}
    except BaseException:
        observation.run_end(child_id, "cancelled", "continuation claim did not complete")
        raise
    return {**started, "parent_run_id": run_id, "claimed": True, "auto_executed": False,
            "resume_prompt": recovery.markdown(value), "reason": "continue in this session using the new run id"}


def import_rows(db, rows):
    for value in rows:
        if set(value) != {"parent_run_id", "child_run_id"}:
            raise ValueError("invalid continuation row")
        parent, child = db.run(value["parent_run_id"]), db.run(value["child_run_id"])
        if child["parent_run_id"] != parent["run_id"] or child["run_id"] == parent["run_id"]:
            raise ValueError("continuation lineage differs from event history")
        for key in ("project_id", "task_id", "role"):
            if child[key] != parent[key]:
                raise ValueError("continuation context differs")
        if child["ts"] <= parent["ts"]:
            raise ValueError("continuation must follow parent chronologically")
        previous = db.connection.execute("SELECT child_run_id FROM continuations WHERE parent_run_id=?", (parent["run_id"],)).fetchone()
        if previous and previous[0] != child["run_id"]:
            raise ValueError("conflicting continuation")
        if not previous:
            db.connection.execute("INSERT INTO continuations VALUES(?,?)", (parent["run_id"], child["run_id"]))
