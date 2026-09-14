import tempfile
import sys
import sqlite3
import unittest
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-server/src"))
from agent_platform_mcp import events
from agent_platform_mcp.tools import store


def started():
    return events.RunEvent(str(uuid4()), str(uuid4()), None, "project-one", "sample-task", "reviewer",
                           "run_started", "2026-09-14T00:00:00Z", "codex", None, {}, {}, "direct", "partial")


class StoreTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name).resolve() / "state.db"
        self.db = store.open(self.path)
        self.addCleanup(self.db.close)
        self.start = started()
        self.db.record_event(self.start)

    def test_version_dedup_conflicting_identity_and_foreign_run(self):
        self.assertEqual(self.db.connection.execute("PRAGMA user_version").fetchone()[0], 3)
        self.assertFalse(self.db.record_event(self.start))
        with self.assertRaises(ValueError):
            self.db.record_event(replace(self.start, model="different"))
        with self.assertRaises(ValueError):
            self.db.record_event(replace(self.start, event_id=str(uuid4()), run_id=str(uuid4()), event_type="run_ended", payload={"outcome": "completed"}))
        self.assertEqual(len(self.db.runs()), 1)

    def test_end_context_and_time_checks(self):
        end = replace(self.start, event_id=str(uuid4()), event_type="run_ended", payload={"outcome": "completed"})
        for bad in (replace(end, project_id="other"), replace(end, ts="2026-09-13T00:00:00Z"),
                    replace(end, payload={"outcome": "approved"})):
            with self.assertRaises(ValueError):
                self.db.record_event(bad)
        self.assertTrue(self.db.record_event(end))
        self.assertEqual(self.db.run(end.run_id)["outcome"], "completed")
        with self.assertRaises(ValueError):
            self.db.record_event(replace(end, event_id=str(uuid4())))

    def test_null_zero_usage_snapshot_and_conflict(self):
        self.db.record_usage(self.start.run_id, events.Usage(None, None, None, None, "unavailable", "unavailable"))
        row = self.db.connection.execute("SELECT payload_json FROM usage").fetchone()[0]
        self.assertIn('"input_tokens": null', row)
        usage = events.Usage(0, 10, 0, None, "fixture", "full")
        self.db.record_usage(self.start.run_id, usage)
        self.db.record_usage(self.start.run_id, usage)
        self.assertEqual(self.db.connection.execute("SELECT count(*) FROM usage").fetchone()[0], 1)
        with self.assertRaises(ValueError):
            self.db.record_usage(self.start.run_id, replace(usage, input_tokens=12))

    def test_role_specific_rejections_and_duplicate_decisions(self):
        cycle = str(uuid4())
        def decision(role, attempt, status, fingerprint="a" * 64):
            return events.ReviewResult(str(uuid4()), cycle, str(uuid4()), "human", role, attempt, status,
                                       fingerprint, None, "docs/features/sample-task/REVIEW.md")
        result = decision("reviewer", 1, "rejected")
        self.assertTrue(self.db.record_review(result, "project-one", "sample-task"))
        self.assertFalse(self.db.record_review(result, "project-one", "sample-task"))
        with self.assertRaises(ValueError):
            self.db.record_review(replace(result, decision="approved"), "project-one", "sample-task")
        with self.assertRaises(ValueError):
            self.db.record_review(decision("reviewer", 1, "approved"), "project-one", "sample-task")
        for result in (decision("reviewer", 2, "rejected"), decision("reviewer", 3, "rejected", "b" * 64),
                       decision("security", 1, "rejected")):
            self.db.record_review(result, "project-one", "sample-task")
        self.assertTrue(self.db.review_status("project-one", "sample-task")["reviewer"]["intervention_recommended"])
        self.db.record_review(decision("reviewer", 4, "approved"), "project-one", "sample-task")
        status = self.db.review_status("project-one", "sample-task")
        self.assertEqual(status["reviewer"]["consecutive_rejections"], 0)
        self.assertEqual(status["security"]["consecutive_rejections"], 1)

    def test_raw_payload_and_known_secret_rejected(self):
        for payload in ({"stdout": "private source"}, {"workspace": "api_key=example-value"}):
            with self.assertRaises(ValueError):
                self.db.record_event(replace(self.start, event_id=str(uuid4()), run_id=str(uuid4()), payload=payload))

    def test_future_schema_and_symlink_fail_closed(self):
        self.db.connection.execute("PRAGMA user_version=999")
        with self.assertRaises(store.StoreError):
            store.open(self.path)
        link = self.path.parent / "linked.db"
        link.symlink_to(self.path)
        with self.assertRaises(store.StoreError):
            store.open(link)

    def test_reopen_persistence_and_isolated_project_query(self):
        with store.open(self.path) as other:
            self.assertEqual(other.run(self.start.run_id)["task_id"], "sample-task")
            self.assertEqual(other.runs("other-project"), [])
            self.assertEqual(other.runs(since="2026-09-15T00:00:00Z"), [])

    def test_schema_one_migration_preserves_run_history(self):
        path = self.path.parent / "old.db"
        with sqlite3.connect(path) as old:
            old.executescript(store.SCHEMA + "PRAGMA user_version=1;")
            row = self.db.connection.execute("SELECT * FROM runs").fetchone()
            old.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", tuple(row))
        with store.open(path) as migrated:
            self.assertEqual(migrated.connection.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(migrated.connection.execute("SELECT count(*) FROM evidence").fetchone()[0], 0)
            self.assertEqual(migrated.run(self.start.run_id)["task_id"], "sample-task")
