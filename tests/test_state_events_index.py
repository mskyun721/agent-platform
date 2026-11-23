"""events(run_id, ts) index, user_version 8 (DBA F-12, F-13) and the close-stale follow-ups (REVIEW N-13, N-15)."""
import json
import sqlite3
import tempfile
import time
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from test_usage_attribution_stale import StaleFixture

from agent_platform_mcp import cli
from agent_platform_mcp.tools import llm_view, observation, recovery, state_queries, store, usage_efficiency

SLO_SEC = 1.0


def plan(connection, sql, params):
    return " ".join(row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + sql, params))


class MigrationTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name).resolve() / "state.db"

    def seven(self):
        """A user_version 7 DB: every table, no events_run index."""
        with store.open(self.path) as db:
            db.connection.executescript("DROP INDEX events_run; PRAGMA user_version=7;")

    def test_version_seven_gains_the_index_and_keeps_its_rows(self):
        self.seven()
        with sqlite3.connect(self.path) as old:
            old.execute("INSERT INTO runs VALUES ('r1','{}','p','t','2026-01-01T00:00:00+00:00',NULL,NULL)")
            old.execute("INSERT INTO events VALUES ('e1','r1','run_started','2026-01-01T00:00:00+00:00','{}')")
        with store.open(self.path) as db:
            self.assertEqual(db.connection.execute("PRAGMA user_version").fetchone()[0], store.SCHEMA_VERSION)
            self.assertEqual(store.SCHEMA_VERSION, 8)
            columns = [row[2] for row in db.connection.execute("PRAGMA index_info(events_run)")]
            self.assertEqual(columns, ["run_id", "ts"])
            self.assertEqual(db.connection.execute("SELECT count(*) FROM events").fetchone()[0], 1)

    def test_a_failed_migration_leaves_version_seven(self):
        self.seven()
        with sqlite3.connect(self.path) as old:
            old.executescript("DROP TABLE events;")  # CREATE INDEX fails inside the migration transaction
        with self.assertRaises(store.StoreError):
            store.open(self.path)
        with sqlite3.connect(self.path) as old:
            self.assertEqual(old.execute("PRAGMA user_version").fetchone()[0], 7)
            self.assertIsNone(old.execute("SELECT 1 FROM sqlite_master WHERE name='events_run'").fetchone())

    def test_read_only_readers_accept_seven_and_eight_only(self):
        store.open(self.path).close()
        for version, readable in ((8, True), (7, True), (6, False), (9, False)):
            with sqlite3.connect(self.path) as raw:
                raw.execute(f"PRAGMA user_version={version}")
            connection, reason = store.open_readonly(self.path)
            with self.subTest(version=version):
                self.assertEqual(connection is not None, readable, reason)
            if connection:
                connection.close()

    def test_a_version_eight_db_without_the_index_rebuilds_it_on_open(self):  # DBA F-15, REVIEW N-19
        store.open(self.path).close()
        with sqlite3.connect(self.path) as raw:
            raw.executescript("DROP INDEX events_run;")  # the partial rollback: user_version stays 8
        with store.open(self.path) as db:
            self.assertEqual(db.connection.execute("PRAGMA user_version").fetchone()[0], 8)
            self.assertEqual([row[2] for row in db.connection.execute("PRAGMA index_info(events_run)")], ["run_id", "ts"])
            self.assertIn("USING COVERING INDEX events_run", plan(db.connection, state_queries.NEWER, ("r", 0)))

    def test_opening_an_indexed_version_eight_db_runs_no_ddl(self):  # DBA F-15: the check comes before the write lock
        store.open(self.path).close()
        statements = []
        original = sqlite3.connect
        def traced(*args, **kwargs):
            connection = original(*args, **kwargs)
            connection.set_trace_callback(statements.append)
            return connection
        with unittest.mock.patch.object(store.sqlite3, "connect", side_effect=traced):
            store.open(self.path).close()
        self.assertFalse([sql for sql in statements if "CREATE" in sql or "BEGIN" in sql], statements)

    def test_rollback_to_seven_needs_the_version_too(self):  # ADR-015: DROP INDEX plus user_version=7
        store.open(self.path).close()
        with sqlite3.connect(self.path) as raw:
            raw.executescript("DROP INDEX events_run; PRAGMA user_version=7;")
            self.assertEqual(raw.execute("PRAGMA user_version").fetchone()[0], 7)
            self.assertIsNone(raw.execute("SELECT 1 FROM sqlite_master WHERE name='events_run'").fetchone())

    def test_per_run_event_reads_search_the_index(self):
        with store.open(self.path) as db:
            for sql, params in (("SELECT event_json FROM events WHERE run_id=? AND event_type='run_ended' ORDER BY rowid DESC LIMIT 1", ("r",)),
                                ("SELECT event_json FROM events WHERE run_id=? ORDER BY ts,rowid", ("r",)),
                                ("SELECT 1 FROM events WHERE run_id=?", ("r",)),  # the FK check of a cascading DELETE
                                (state_queries.NEWER, ("r", 0))):
                with self.subTest(sql=sql):
                    self.assertIn("USING INDEX events_run", plan(db.connection, sql, params).replace("COVERING ", ""))


def bulk(runs, per_run, opened):
    """`runs` raw runs with `per_run` events each; the newest `opened` runs of every 20 stay open."""
    now = datetime.now(timezone.utc)
    rows, items = [], []
    for index in range(runs):
        run_id, start = str(uuid4()), now - timedelta(days=400) + timedelta(seconds=index * 600)
        open_run = index >= runs - opened * 20 and index % 20 == 0
        event = {"event_id": str(uuid4()), "run_id": run_id, "parent_run_id": None, "project_id": "p1", "task_id": "t",
                 "role": "backend", "event_type": "run_started", "ts": start.isoformat(), "backend": "claude", "model": "m",
                 "skill_versions": {}, "payload": {"workspace": "/w"}, "collection_source": "direct", "completeness": "partial",
                 "schema_version": 1}
        end = None if open_run else (start + timedelta(minutes=5)).isoformat()
        rows.append((run_id, json.dumps(event), "p1", "t", start.isoformat(), end, None if open_run else "completed"))
        items.append((event["event_id"], run_id, "run_started", start.isoformat(), json.dumps(event)))
        items.extend((str(uuid4()), run_id, "handoff", (start + timedelta(seconds=step)).isoformat(), "{}") for step in range(1, per_run))
    with store.open() as db, db.connection:
        db.connection.executemany("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", rows)
        db.connection.executemany("INSERT INTO events VALUES(?,?,?,?,?)", items)
    return rows


class IndexPerformanceTest(unittest.TestCase):  # DBA F-12: 300k events (30k runs x 10)
    def test_prune_and_a_full_viewer_page_stay_under_the_slo(self):
        rows = bulk(30_000, 10, 25)
        page_start = time.perf_counter()
        page = llm_view.list_runs(500)
        listed = time.perf_counter() - page_start
        boundary = datetime.fromisoformat(rows[100][4]).isoformat()  # the 100 oldest runs
        prune_start = time.perf_counter()
        removed = state_queries.prune(before=boundary)["removed_runs"]
        pruned = time.perf_counter() - prune_start
        print(f"\nlist_runs(500) {listed:.3f}s; prune {removed} runs {pruned:.3f}s")
        self.assertEqual(sum(run["ended_at"] is None for run in page["runs"]), 25)
        self.assertEqual(removed, 100)
        self.assertLess(listed, SLO_SEC)
        self.assertLess(pruned, SLO_SEC)
        with store.open() as db:
            self.assertEqual(db.connection.execute("SELECT count(*) FROM events").fetchone()[0], 299_000)


class CloseStaleFollowUpTest(StaleFixture, unittest.TestCase):
    def control(self, run_id, state):
        old = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
        with store.open() as db, db.connection:
            db.connection.execute("INSERT INTO run_control VALUES (?,?,?,?,?,?)", (run_id, state, old, None, None, "done"))
        return old

    def test_a_completed_recovery_state_is_ended_completed(self):  # REVIEW N-13 (probe Y)
        done, lost = self.started(days=10), self.started(days=10)
        heartbeat = self.control(done, "completed")
        preview = {item["run_id"]: item["outcome"] for item in state_queries.close_stale("7d", dry_run=True)["runs"]}
        self.assertEqual(preview, {done: "completed", lost: "abandoned"})
        self.assertEqual(sorted(state_queries.close_stale("7d")["run_ids"]), sorted([done, lost]))
        with store.open() as db:
            run = db.run(done)
            self.assertEqual((run["outcome"], run["state"], run["ended_at"]), ("completed", "completed", store._timestamp(heartbeat)))
            self.assertEqual(db.run(lost)["state"], "cancelled")
            runs = [db.run(done), db.run(lost)]
        summary = usage_efficiency.summarize(runs, total=2, limit=2)
        self.assertEqual(sum(group["failed_or_interrupted"] for group in summary["groups"]), 1)
        self.assertEqual(recovery.resume(done)["verdict"], "done")
        with store.open() as db:  # REVIEW N-17: the state did not change, so neither did its reason
            reasons = dict(db.connection.execute("SELECT run_id,reason FROM run_control WHERE run_id IN (?,?)", (done, lost)).fetchall())
            ended = db.connection.execute("SELECT event_json FROM events WHERE run_id=? AND event_type='run_ended'", (done,)).fetchone()[0]
        self.assertEqual(reasons, {done: "done", lost: "open run closed by state close-stale"})
        self.assertEqual(json.loads(ended)["payload"]["reason"], "state end recorded by state close-stale")

    def test_state_end_changes_the_recovery_reason_only_with_the_state(self):  # REVIEW N-17 (probe B)
        cases = (("completed", "completed", None, "done"), ("running", "completed", None, None),
                 ("completed", "failed", "tests failed", "tests failed"), ("waiting", "completed", "x", "done"))
        for before, outcome, reason, expected in cases:
            with self.subTest(before=before, outcome=outcome):
                run = self.started(days=1)
                self.control(run, before)
                with store.open() as db:
                    payload = {"outcome": outcome} | ({"reason": reason} if reason else {})
                    db.record_event(observation._derived(db.run(run), "run_ended", payload))
                    self.assertEqual(db.connection.execute("SELECT reason FROM run_control WHERE run_id=?", (run,)).fetchone()[0], expected)

    def test_close_stale_without_the_index_uses_the_plain_read(self):  # DBA F-15, REVIEW N-19 (probe F)
        run = self.started(days=10)
        with store.open() as db:
            db.connection.executescript("DROP INDEX events_run;")
        with unittest.mock.patch.object(store, "EVENTS_INDEX", ""):  # the index stays missing for this run
            result = state_queries.close_stale("7d")
        self.assertEqual((result["run_ids"], result["stopped"]), ([run], None))
        with store.open() as db:  # the next normal open repairs it
            self.assertIsNotNone(db.connection.execute("SELECT 1 FROM sqlite_master WHERE name='events_run'").fetchone())


class PruneBatchTest(StaleFixture, unittest.TestCase):  # DBA F-14
    def ended(self, count):
        rows = bulk(count, 1, 0)
        return [row[0] for row in rows]

    def test_prune_commits_each_batch_in_its_own_short_transaction(self):
        runs = self.ended(7)
        with store.open() as db, db.connection:  # a pinned run in the first batch stays and does not stall the rest
            db.connection.execute("INSERT INTO checkpoints VALUES(?,1,?)",
                                  (sorted(runs)[0], "{}"))
        statements = []
        original = store.open
        def traced(*args, **kwargs):
            db = original(*args, **kwargs)
            db.connection.set_trace_callback(statements.append)
            return db
        with unittest.mock.patch.object(state_queries, "PRUNE_BATCH", 3), unittest.mock.patch.object(state_queries.store, "open", side_effect=traced):
            result = state_queries.prune(retention_days=1)
        self.assertEqual((result["removed_runs"], result["batches"]), (6, 3))
        transactions, current = [], None
        for sql in statements:
            if sql.startswith("BEGIN"):
                current = []
            elif sql.startswith("COMMIT") and current is not None:
                transactions.append(current)
                current = None
            elif current is not None and sql.startswith("DELETE FROM runs"):
                current.append(sql)
        # The trace repeats a DELETE once per FK cascade sub-program, so distinct statements count the runs.
        self.assertEqual([len(set(deletes)) for deletes in transactions], [2, 3, 1])
        with store.open() as db:
            self.assertEqual([row[0] for row in db.connection.execute("SELECT run_id FROM runs")], [sorted(runs)[0]])

    def test_the_default_batch_size_is_five_thousand_runs(self):
        self.assertEqual(state_queries.PRUNE_BATCH, 5000)

    def test_a_storage_error_stops_with_the_runs_closed_so_far(self):  # REVIEW N-15
        for error in (sqlite3.OperationalError("database is locked"), sqlite3.IntegrityError("constraint")):
            with self.subTest(error=type(error).__name__):
                first, second, third = self.started(days=12), self.started(days=11), self.started(days=10)
                original = store.Store.apply_event
                def fail_second(self_, event, encoded=None):
                    if event.run_id == second:
                        raise error
                    return original(self_, event, encoded)
                with unittest.mock.patch.object(store.Store, "apply_event", autospec=True, side_effect=fail_second):
                    result = state_queries.close_stale("7d")
                stopped = f"storage error: {type(error).__name__}"
                self.assertEqual((result["run_ids"], result["closed"], result["stopped"], result["unprocessed"]), ([first], 1, stopped, 1))
                self.assertEqual(result["skipped"], {stopped: 1})
                with store.open() as db:
                    self.assertEqual([db.run(run_id)["ended_at"] is None for run_id in (first, second, third)], [False, True, True])
                    self.assertIsNone(db.connection.execute("SELECT 1 FROM run_control WHERE run_id=?", (second,)).fetchone())
                again = state_queries.close_stale("7d")
                self.assertEqual((sorted(again["run_ids"]), again["stopped"]), (sorted([second, third]), None))

    def test_the_cli_exits_one_when_close_stale_stopped(self):
        for stopped, code in (("storage error: OperationalError", 1), (None, 0)):
            with self.subTest(stopped=stopped), unittest.mock.patch.object(state_queries, "close_stale", return_value={"stopped": stopped}), \
                    unittest.mock.patch("sys.stdout"):
                self.assertEqual(cli.main(["state", "close-stale"]), code)

    def test_import_rejects_a_live_control_row_on_an_abandoned_run(self):  # REVIEW N-15
        run = self.started(days=10)
        state_queries.close_stale("7d")
        with store.open() as db, db.connection:
            db.connection.execute("DELETE FROM run_control WHERE run_id=?", (run,))
            row = {"run_id": run, "state": "waiting", "heartbeat_at": recovery.now(), "pid": None, "host": None, "reason": None}
            with self.assertRaisesRegex(ValueError, "conflicts with terminal event"):
                recovery.import_rows(db, {"run_control": [row], "checkpoints": []})
            recovery.import_rows(db, {"run_control": [row | {"state": "cancelled"}], "checkpoints": []})


if __name__ == "__main__":
    unittest.main()
