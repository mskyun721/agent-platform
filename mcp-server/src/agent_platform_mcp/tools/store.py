"""Local SQLite event storage with explicit metadata-only contracts."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from agent_platform_mcp import config, events
from agent_platform_mcp.tools import pricing, projects
from agent_platform_mcp.tools.stdout_artifacts import _mask


class StoreError(RuntimeError):
    pass


PAYLOAD_FIELDS = {
    "run_started": {"workspace", "skill_versions_source", "source_session_id", "price_snapshot"},
    "run_ended": {"outcome", "reason", "duration_sec"},
    "handoff": {"from_agent", "to_agent", "purpose", "passed", "artifact_status", "verification_status", "policy_status"},
    "verification": {"profile_id", "status", "exit_code", "duration_sec", "code_fingerprint"},
    "usage": set(events.Usage.__dataclass_fields__),
    "review_result": set(events.ReviewResult.__dataclass_fields__),
}
SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
 run_id TEXT PRIMARY KEY, event_json TEXT NOT NULL, project_id TEXT, task_id TEXT NOT NULL,
 started_at TEXT NOT NULL, ended_at TEXT, outcome TEXT);
CREATE TABLE IF NOT EXISTS events (
 event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
 event_type TEXT NOT NULL, ts TEXT NOT NULL, event_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS usage (
 run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS review_results (
 decision_id TEXT PRIMARY KEY, project_id TEXT, task_id TEXT NOT NULL, role TEXT NOT NULL,
 review_cycle_id TEXT NOT NULL, attempt INTEGER NOT NULL, payload_json TEXT NOT NULL, ts TEXT NOT NULL,
 UNIQUE(review_cycle_id, role, attempt));
CREATE INDEX IF NOT EXISTS runs_project ON runs(project_id, started_at);
"""


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, allow_nan=False)


def _timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp requires timezone")
    return parsed.astimezone(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.connection = None
        try:
            projects._safe_storage(path)
            if path.suffix != ".db":
                raise ValueError("state storage requires a .db path")
            path.parent.mkdir(parents=True, exist_ok=True)
            for suffix in ("-journal", "-wal", "-shm"):
                projects._safe_storage(Path(str(path) + suffix))
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            self.connection = sqlite3.connect(path, timeout=5)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys=ON")
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2):
                raise ValueError("unsupported state schema version")
            if version == 0:
                self.connection.executescript("BEGIN IMMEDIATE;" + SCHEMA + "PRAGMA user_version=1;COMMIT;")
            if version in (0, 1):
                from agent_platform_mcp.tools.evidence import SCHEMA as EVIDENCE_SCHEMA
                self.connection.executescript("BEGIN IMMEDIATE;" + EVIDENCE_SCHEMA + "PRAGMA user_version=2;COMMIT;")
        except (OSError, sqlite3.Error, ValueError) as exc:
            self.close()
            raise StoreError(f"state storage unavailable: {type(exc).__name__}") from exc

    def close(self):
        if self.connection is not None:
            self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def record_event(self, event: events.RunEvent) -> bool:
        errors = events.validate(event)
        if errors:
            raise ValueError("; ".join(errors))
        if set(event.payload) - PAYLOAD_FIELDS[event.event_type]:
            raise ValueError("event payload contains unsupported or raw fields")
        if event.event_type == "run_started" and event.payload.get("price_snapshot") is not None:
            pricing.validate_snapshot(event.payload["price_snapshot"])
            if event.payload["price_snapshot"]["model"] != event.model:
                raise ValueError("price snapshot model differs from run")
        if any(isinstance(value, str) and len(value) > 1024 for value in event.payload.values()):
            raise ValueError("event metadata string too long")
        if event.event_type == "run_ended" and event.payload.get("outcome") not in {"completed", "failed", "interrupted", "cancelled"}:
            raise ValueError("invalid run outcome")
        encoded = _json(asdict(event))
        if _mask(encoded) != encoded:
            raise ValueError("suspected secret in event metadata")
        try:
            with self.connection:
                self.connection.execute("BEGIN IMMEDIATE")
                existing = self.connection.execute("SELECT event_json FROM events WHERE event_id=?", (event.event_id,)).fetchone()
                if existing:
                    if existing[0] != encoded:
                        raise ValueError("event id reused with different content")
                    return False
                if event.event_type == "run_started":
                    self.connection.execute("INSERT INTO runs(run_id,event_json,project_id,task_id,started_at) VALUES(?,?,?,?,?)",
                                            (event.run_id, encoded, event.project_id, event.task_id, _timestamp(event.ts)))
                else:
                    run = self.run(event.run_id)
                    for key in ("project_id", "task_id", "role", "backend", "model"):
                        if run[key] != getattr(event, key):
                            raise ValueError(f"event {key} differs from run")
                    if event.event_type == "run_ended":
                        if run["ended_at"]:
                            raise ValueError("run is already ended")
                        if _timestamp(event.ts) < run["ts"]:
                            raise ValueError("run end precedes start")
                        self.connection.execute("UPDATE runs SET ended_at=?,outcome=? WHERE run_id=?",
                                                (_timestamp(event.ts), event.payload["outcome"], event.run_id))
                    elif event.event_type == "usage":
                        self._usage(event.run_id, events.Usage(**event.payload))
                    elif event.event_type == "review_result":
                        self._review(events.ReviewResult(**event.payload), event.project_id, event.task_id, event.ts)
                self.connection.execute("INSERT INTO events VALUES(?,?,?,?,?)",
                                        (event.event_id, event.run_id, event.event_type, _timestamp(event.ts), encoded))
            return True
        except sqlite3.IntegrityError as exc:
            raise ValueError("conflicting event or run identity") from exc
        except sqlite3.Error as exc:
            raise StoreError("event storage failed") from exc

    def _usage(self, run_id: str, usage: events.Usage):
        errors = events.validate_usage(usage)
        if errors:
            raise ValueError("; ".join(errors))
        if usage.source.startswith("codex-json:"):
            for row in self.connection.execute("SELECT run_id,payload_json FROM usage WHERE run_id<>?", (run_id,)):
                if json.loads(row[1])["source"] == usage.source:
                    raise ValueError("native source event is already attributed to another run")
        existing = self.connection.execute("SELECT payload_json FROM usage WHERE run_id=?", (run_id,)).fetchone()
        if existing:
            previous = json.loads(existing[0])
            rank = {"unavailable": 0, "partial": 1, "full": 2}
            if rank[usage.completeness] < rank[previous["completeness"]]:
                return
            counts = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
            if any(previous[key] is not None and previous[key] != getattr(usage, key) for key in counts):
                raise ValueError("usage snapshot already recorded; conflicting source/counts")
        self.connection.execute("INSERT OR REPLACE INTO usage VALUES(?,?)", (run_id, _json(asdict(usage))))

    def record_usage(self, run_id: str, usage: events.Usage):
        self.run(run_id)
        try:
            with self.connection:
                self.connection.execute("BEGIN IMMEDIATE")
                self._usage(run_id, usage)
        except sqlite3.Error as exc:
            raise StoreError("usage storage failed") from exc

    def _review(self, result: events.ReviewResult, project_id: str | None, task_id: str, ts: str) -> bool:
        errors = events.validate_review(result)
        if errors:
            raise ValueError("; ".join(errors))
        encoded = _json(asdict(result))
        if _mask(encoded) != encoded:
            raise ValueError("suspected secret in review metadata")
        old = self.connection.execute("SELECT * FROM review_results WHERE decision_id=?", (result.decision_id,)).fetchone()
        if old:
            if old["payload_json"] != encoded or old["project_id"] != project_id or old["task_id"] != task_id:
                raise ValueError("decision id reused with different content")
            return False
        self.connection.execute("INSERT INTO review_results VALUES(?,?,?,?,?,?,?,?)",
                                (result.decision_id, project_id, task_id, result.role, result.review_cycle_id,
                                 result.attempt, encoded, _timestamp(ts)))
        return True

    def record_review(self, result: events.ReviewResult, project_id: str | None, task_id: str) -> bool:
        if result.run_id:
            run = self.run(result.run_id)
            if (run["project_id"], run["task_id"], run["role"]) != (project_id, task_id, result.role):
                raise ValueError("review context differs from run")
        try:
            with self.connection:
                self.connection.execute("BEGIN IMMEDIATE")
                return self._review(result, project_id, task_id, datetime.now(timezone.utc).isoformat())
        except sqlite3.IntegrityError as exc:
            raise ValueError("review attempt already has a decision") from exc
        except sqlite3.Error as exc:
            raise StoreError("review storage failed") from exc

    def run(self, run_id: str) -> dict:
        row = self.connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("unknown run id")
        return {**json.loads(row["event_json"]), "ts": row["started_at"], "ended_at": row["ended_at"], "outcome": row["outcome"]}

    def runs(self, project_id: str | None = None, since: str | None = None) -> list[dict]:
        since = _timestamp(since) if since else None
        rows = self.connection.execute("SELECT run_id FROM runs WHERE (? IS NULL OR project_id=?) AND (? IS NULL OR started_at>=?) ORDER BY started_at,run_id",
                                       (project_id, project_id, since, since))
        return [self.run(row[0]) for row in rows.fetchall()]

    def review_status(self, project_id: str | None, task_id: str, threshold: int = 3) -> dict:
        if type(threshold) is not int or threshold < 1:
            raise ValueError("review threshold must be positive integer")
        results = {}
        rows = self.connection.execute("SELECT role,payload_json FROM review_results WHERE project_id IS ? AND task_id=? ORDER BY rowid",
                                       (project_id, task_id))
        for row in rows:
            decision = json.loads(row["payload_json"])["decision"]
            count = results.get(row["role"], {}).get("consecutive_rejections", 0)
            count = count + 1 if decision == "rejected" else 0
            results[row["role"]] = {"last_decision": decision, "consecutive_rejections": count,
                                    "intervention_recommended": count >= threshold}
        return results


def open(path: str | Path | None = None) -> Store:
    return Store(Path(path or os.environ.get("AGENT_PLATFORM_STATE_DB", config.ROOT / ".local/state.db")).absolute())
