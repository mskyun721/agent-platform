"""Metadata checkpoints and conservative, non-executing resume decisions."""

import json
import math
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

from agent_platform_mcp import config, events
from agent_platform_mcp.tools import fingerprint, projects, store
from agent_platform_mcp.tools.stdout_artifacts import _mask

SCHEMA = """
CREATE TABLE run_control (
 run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
 state TEXT NOT NULL, heartbeat_at TEXT NOT NULL, pid INTEGER, host TEXT, reason TEXT);
CREATE TABLE checkpoints (
 run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
 seq INTEGER NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(run_id,seq));
"""
TRANSITIONS = {
    "pending": {"running", "cancelled"},
    "running": {"waiting", "failed", "interrupted", "cancelled", "completed"},
    "waiting": {"running", "cancelled", "failed", "completed", "interrupted"},
    "failed": {"waiting", "running", "cancelled"},
    "interrupted": {"waiting", "running", "cancelled"},
    "cancelled": set(), "completed": set(),
}


def now():
    return datetime.now(timezone.utc).isoformat()


def metadata(value):
    encoded = json.dumps(value, allow_nan=False)
    if len(encoded) > 2 * 1024 * 1024 or _mask(encoded) != encoded:
        raise ValueError("checkpoint metadata exceeds limits or contains suspected secrets")
    return encoded


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 1024 or any(ord(c) < 32 for c in value):
        raise ValueError("metadata must be a single nonempty line of at most 1024 characters")
    metadata(value)
    return value


def _state(db, run_id):
    run = db.run(run_id)
    row = db.connection.execute("SELECT * FROM run_control WHERE run_id=?", (run_id,)).fetchone()
    return dict(row) if row else {"run_id": run_id, "state": run["outcome"] or "running",
                                  "heartbeat_at": run["ts"], "pid": None, "host": None, "reason": None}


def _save(db, value):
    db.connection.execute("INSERT INTO run_control VALUES(:run_id,:state,:heartbeat_at,:pid,:host,:reason) "
                          "ON CONFLICT(run_id) DO UPDATE SET state=excluded.state, heartbeat_at=excluded.heartbeat_at, "
                          "pid=excluded.pid, host=excluded.host, reason=excluded.reason", value)


def _workspace(run):
    project_id = run["project_id"]
    if not project_id or project_id not in projects._read()["projects"]:
        raise ValueError("resume/checkpoint requires the original registered project")
    context = projects.resolve(run["payload"]["workspace"])
    if context.project_id != project_id:
        raise ValueError("workspace registration changed; inspect the original project before resuming")
    return context.path


def _alive(state):
    if state["pid"] is None:
        return False
    if state["host"] != socket.gethostname():
        return True  # An imported/foreign PID is unknown, never evidence that execution stopped.
    try:
        os.kill(state["pid"], 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def transition(run_id: str, state: str, reason: str | None = None):
    if state not in TRANSITIONS:
        raise ValueError("unknown run state")
    if reason is not None:
        _text(reason)
    with store.open() as db, db.connection:
        db.connection.execute("BEGIN IMMEDIATE")
        current = _state(db, run_id)
        if state != current["state"] and state not in TRANSITIONS[current["state"]]:
            raise ValueError(f"invalid transition {current['state']} to {state}")
        if state == "running" and current["state"] != "running" and _alive(current):
            raise ValueError("previous process is still alive or unknown")
        current.update(state=state, reason=reason, heartbeat_at=now())
        if state == "running":
            current.update(pid=None, host=None)
        _save(db, current)
        return current


def heartbeat(run_id: str, pid: int):
    if type(pid) is not int or pid < 1:
        raise ValueError("heartbeat requires a positive caller process id")
    with store.open() as db, db.connection:
        db.connection.execute("BEGIN IMMEDIATE")
        current = _state(db, run_id)
        if current["state"] != "running":
            raise ValueError("only a running execution can heartbeat")
        if current["pid"] != pid and _alive(current):
            raise ValueError("another process already owns this run")
        current.update(pid=pid, host=socket.gethostname(), heartbeat_at=now())
        _save(db, current)
        return current


def checkpoint(run_id: str, phase: str, next_action: str, decisions: list[str] | None = None,
               unresolved: list[str] | None = None, verification: list[str] | None = None,
               artifacts: list[str] | None = None):
    _text(phase)
    _text(next_action)
    fields = {"decisions": decisions or [], "unresolved": unresolved or [],
              "verification": verification or [], "artifacts": artifacts or []}
    for values in fields.values():
        if not isinstance(values, list) or len(values) > 100:
            raise ValueError("checkpoint lists must contain at most 100 entries")
        for value in values:
            _text(value)
    for path in fields["artifacts"]:
        if not path.startswith("docs/") or ".." in Path(path).parts or "\\" in path or any(word in path.lower() for word in (".env", ".pem", ".key", "secret", "credential")):
            raise ValueError("artifacts require non-secret docs-relative paths")
    with store.open() as db, db.connection:
        db.connection.execute("BEGIN IMMEDIATE")
        run = db.run(run_id)
        if _state(db, run_id)["state"] in {"completed", "cancelled"}:
            raise ValueError("cannot checkpoint a terminal run")
        workspace = _workspace(run)
        for reference in fields["verification"]:
            if not events._uuid(reference):
                raise ValueError("verification references require run UUIDs")
            verified = db.run(reference)
            if (verified["project_id"], verified["task_id"]) != (run["project_id"], run["task_id"]):
                raise ValueError("verification reference belongs to another task")
        for path in fields["artifacts"]:
            target = workspace / path
            projects._safe_storage(target)
            if not target.is_file():
                raise ValueError("checkpoint artifact must exist")
        seq = db.connection.execute("SELECT COALESCE(MAX(seq),0)+1 FROM checkpoints WHERE run_id=?", (run_id,)).fetchone()[0]
        value = {"run_id": run_id, "seq": seq, "ts": now(), "workspace": str(workspace),
                 "snapshot": fingerprint.code_fingerprint(workspace), "phase": phase, "next_action": next_action, **fields}
        db.connection.execute("INSERT INTO checkpoints VALUES(?,?,?)", (run_id, seq, metadata(value)))
        return value


def markdown(value):
    lines = ["# Run Checkpoint", f"Run: {value['run_id']}", f"Phase: {value['phase']}",
             f"Fingerprint: {value['snapshot']['fingerprint']}", f"Next action: {value['next_action']}"]
    for field in ("decisions", "unresolved", "verification", "artifacts"):
        lines += [f"## {field.title()}", *[f"- {item}" for item in value[field]]]
    return "\n".join(lines) + "\n"


def export_rows(db):
    return {table: [dict(row) for row in db.connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in ("run_control", "checkpoints")}


def import_rows(db, data):
    if not isinstance(data, dict) or set(data) != {"run_control", "checkpoints"}:
        raise ValueError("invalid recovery snapshot")
    for table, fields in (("run_control", ("run_id", "state", "heartbeat_at", "pid", "host", "reason")),
                          ("checkpoints", ("run_id", "seq", "payload_json"))):
        for value in data[table]:
            if set(value) != set(fields):
                raise ValueError("invalid recovery row")
            metadata(value)
            run = db.run(value["run_id"])
            if table == "run_control":
                if value["state"] not in TRANSITIONS or (value["pid"] is not None and (type(value["pid"]) is not int or value["pid"] < 1)):
                    raise ValueError("invalid recovery state")
                store._timestamp(value["heartbeat_at"])
                if run["outcome"] in {"completed", "cancelled"} and value["state"] != run["outcome"]:
                    raise ValueError("recovery state conflicts with terminal event")
                where, keys = "run_id=?", (value["run_id"],)
            else:
                payload = json.loads(value["payload_json"])
                if type(value["seq"]) is not int or value["seq"] < 1 or payload.get("run_id") != value["run_id"] or payload.get("seq") != value["seq"]:
                    raise ValueError("invalid checkpoint identity")
                if set(payload) != {"run_id", "seq", "ts", "workspace", "snapshot", "phase", "next_action", "decisions", "unresolved", "verification", "artifacts"}:
                    raise ValueError("invalid checkpoint fields")
                if payload["workspace"] != run["payload"]["workspace"]:
                    raise ValueError("checkpoint workspace differs from run")
                if fingerprint._hash(payload["snapshot"]["files"]) != payload["snapshot"]["fingerprint"]:
                    raise ValueError("checkpoint manifest hash differs")
                where, keys = "run_id=? AND seq=?", (value["run_id"], value["seq"])
            previous = db.connection.execute(f"SELECT * FROM {table} WHERE {where}", keys).fetchone()
            if previous and dict(previous) != value:
                raise ValueError("conflicting recovery snapshot; do not overwrite live state")
            if not previous:
                db.connection.execute(f"INSERT INTO {table} VALUES({','.join('?' for _ in fields)})", tuple(value[key] for key in fields))


def resume(run_id: str):
    settings = config.agent_config().get("resume", {})
    stale_after = settings.get("stale_after_sec", 600)
    if type(stale_after) not in (int, float) or not math.isfinite(stale_after) or stale_after <= 0:
        raise ValueError("resume.stale_after_sec must be positive and finite")
    with store.open() as db, db.connection:
        db.connection.execute("BEGIN IMMEDIATE")
        run = db.run(run_id)
        state = _state(db, run_id)
        result = {"run_id": run_id, "state": state["state"], "auto_executed": False,
                  "resume_mode": "manual_checkpoint", "workspace_diff": [], "processes": [], "checkpoint": None}
        result["actions"] = [dict(row) for row in db.connection.execute("SELECT * FROM actions WHERE run_id=? ORDER BY rowid", (run_id,))]
        if state["state"] in {"completed", "cancelled"}:
            return {**result, "verdict": "done", "reason": "terminal execution; start a new run for new work"}
        workspace = _workspace(run)
        fresh = (datetime.now(timezone.utc) - datetime.fromisoformat(state["heartbeat_at"])).total_seconds() < stale_after
        if _alive(state) or (state["state"] == "running" and fresh and state["pid"] is None):
            return {**result, "verdict": "running", "processes": [state["pid"]] if state["pid"] else [],
                    "reason": "live/unknown process or fresh heartbeat; do not start a duplicate"}
        if state["state"] == "running":
            state.update(state="interrupted", reason="heartbeat expired or recorded process stopped")
            _save(db, state)
            result["state"] = "interrupted"
        row = db.connection.execute("SELECT payload_json FROM checkpoints WHERE run_id=? ORDER BY seq DESC LIMIT 1", (run_id,)).fetchone()
        if row is None:
            return {**result, "verdict": "no_checkpoint", "reason": "inspect workspace and start a new run"}
        value = json.loads(row[0])
        current = fingerprint.code_fingerprint(workspace)
        before = value["snapshot"]["files"]
        after = current["files"]
        changed = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
        diverged = current["fingerprint"] != value["snapshot"]["fingerprint"]
        return {**result, "verdict": "diverged" if diverged else "resumable", "checkpoint": value,
                "workspace_diff": changed, "next_action": value["next_action"],
                "reason": "review changed paths and reverify before continuing" if diverged else state["reason"],
                "resume_prompt": markdown(value) + "Continue in a new session after reviewing this checkpoint.\n",
                "resume_hint": None, "automatic_resume_supported": False}
