"""Stale open runs (DBA F-7), state.db errors per file (REVIEW N-6), pending sums (N-7), distinct runs_updated
and the human-run `state close-stale`."""
import os
import socket
import sqlite3
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from test_usage_attribution import AttributionFixture, claude_rows
from test_usage_attribution_limits import SLO_SEC, match_seconds, synthetic_runs, synthetic_turns

from agent_platform_mcp import events
from agent_platform_mcp.tools import llm_view, recovery, state_queries, store, usage_attribution


def open_stale(state, now, fraction):
    """Leaves `fraction` of the runs open: only claude/codex runs older than MAX_OPEN plus a day, no session id."""
    boundary = (now - usage_attribution.MAX_OPEN - timedelta(days=1)).isoformat()
    ids = [row[0] for row in state.connection.execute(
        "SELECT run_id FROM runs WHERE started_at<? AND json_extract(event_json,'$.backend') IS NOT NULL ORDER BY started_at",
        (boundary,))]
    total = state.connection.execute('SELECT count(*) FROM runs').fetchone()[0]
    chosen = ids[::max(1, round(len(ids) / (total * fraction)))] if fraction else []
    state.connection.executemany('UPDATE runs SET ended_at=NULL,outcome=NULL WHERE run_id=?', [(run_id,) for run_id in chosen])
    state.connection.commit()
    return len(chosen)


class StaleOpenRunTest(unittest.TestCase):  # DBA F-7 regression: 100k runs, 5% stale open runs without a session id
    def test_stale_open_runs_are_neither_loaded_nor_matched(self):
        now = datetime.now(timezone.utc)
        turns = synthetic_turns(500, now)
        with store.open() as state:
            synthetic_runs(state, 100_000, now)
            _, _, baseline = match_seconds(state, turns, now)
            opened = open_stale(state, now, 0.05)
            elapsed, runs, plan = match_seconds(state, turns, now)
            stale = usage_attribution.stale_open(state, now)
        self.assertGreaterEqual(opened, 4500)
        self.assertEqual(stale, opened)
        self.assertLess(elapsed, SLO_SEC, f'matching took {elapsed:.3f}s')
        self.assertLess(sum(len(group['open']) for group in runs.values()), 50)  # only the SQL day of slack
        self.assertEqual([row[6] for row in plan['rows']], [row[6] for row in baseline['rows']])
        self.assertEqual(plan['counts']['ambiguous'], 0)

    def test_open_run_bound_matches_the_turn_retention(self):
        self.assertEqual(usage_attribution.MAX_OPEN.total_seconds(), llm_view.RETENTION)
        now = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)
        def run(days):
            return {'run_id': f'r{days}', 'source': 'direct', 'session': None, 'start': now - timedelta(days=days), 'end': None}
        runs = {('claude', 'p1'): usage_attribution._group([run(8), run(6)])}
        turn = {'run_id': 't', 'project_id': 'p1', 'workspace': '/w', 'backend': 'claude', 'usage': {'input_tokens': 1},
                'ts': now.isoformat(), 'ended_at': (now + timedelta(minutes=1)).isoformat()}
        self.assertEqual(usage_attribution.decide(turn, runs, now + timedelta(hours=1)), ('attributed', 'r6', ['r6']))


class StaleFixture(AttributionFixture):
    def started(self, days, backend='claude'):
        """An open run started `days` ago (no `state end`)."""
        ts = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        event = events.RunEvent(str(uuid4()), str(uuid4()), None, 'test-project', 'old', 'backend', 'run_started', ts,
                                backend, 'm', {}, {'workspace': str(self.root)}, 'direct', 'partial')
        with store.open() as db:
            db.record_event(event)
        return event.run_id


class CollectStateErrorTest(StaleFixture, unittest.TestCase):
    def test_candidate_load_error_skips_attribution_and_keeps_collecting(self):  # REVIEW N-6 (probe O)
        run = self.start('pay', '00:00:00', '00:10:00')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        with unittest.mock.patch.object(usage_attribution, 'candidates', side_effect=sqlite3.OperationalError('database is locked')):
            result = self.collect()
        self.assertEqual((result['claude']['imported'], result['claude']['errors']), (1, 0))
        self.assertEqual(result['attribution_skipped'], 'state unavailable: OperationalError')
        with self.view.content_db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM native_files').fetchone()[0], 0)
        self.assertEqual(self.collect()['claude']['attribution']['attributed'], 1)
        self.assertEqual(self.usage(run)['input_tokens'], 10)

    def test_failed_sum_is_rewritten_after_its_transcript_is_gone(self):  # REVIEW N-7
        run = self.start('pay', '00:00:00', '00:10:00')
        path = self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        with unittest.mock.patch.object(store.Store, 'attributed_usage', side_effect=store.StoreError('x')):
            self.collect()
        path.unlink()
        result = self.collect()
        self.assertEqual((result['resynced_runs'], self.usage(run)['input_tokens']), (1, 10))
        with self.view.content_db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM native_pending').fetchone()[0], 0)

    def test_runs_updated_counts_distinct_runs(self):
        run = self.start('pay', '00:00:00', '00:10:00')
        self.write('a.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        self.write('b.jsonl', claude_rows(str(self.root), 'u2', '00:03:00', '00:04:00'))
        result = self.collect()
        self.assertEqual(result['claude']['attribution']['attributed'], 2)
        self.assertEqual(result['claude']['attribution']['runs_updated'], 1)
        self.assertEqual(self.usage(run)['input_tokens'], 20)

    def test_collect_reports_stale_open_runs(self):
        self.started(days=9)
        self.start('pay', '00:00:00', '00:10:00')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        self.assertEqual(self.collect()['stale_open_runs'], 1)


class CloseStaleTest(StaleFixture, unittest.TestCase):
    def test_close_stale_ends_only_old_runs_without_a_live_process(self):
        old, recent, alive = self.started(days=10), self.started(days=2), self.started(days=10)
        with store.open() as db, db.connection:
            db.connection.execute('INSERT INTO run_control VALUES (?,?,?,?,?,?)',
                                  (alive, 'running', recovery.now(), os.getpid(), socket.gethostname(), None))
        preview = state_queries.close_stale('7d', dry_run=True)
        self.assertEqual((preview['run_ids'], preview['closed'], preview['kept_live']), ([old], 0, 1))
        with store.open() as db:
            self.assertIsNone(db.run(old)['ended_at'])
        result = state_queries.close_stale()
        self.assertEqual((result['closed'], result['run_ids']), (1, [old]))
        with store.open() as db:
            self.assertEqual(db.run(old)['outcome'], 'abandoned')
            self.assertIsNone(db.run(recent)['ended_at'])
            self.assertIsNone(db.run(alive)['ended_at'])
            self.assertEqual(usage_attribution.stale_open(db, datetime.now(timezone.utc)), 1)  # the live one stays
        self.assertEqual(state_queries.close_stale()['closed'], 0)

    def test_close_stale_marks_a_dead_control_row_terminal(self):
        old = self.started(days=10)
        with store.open() as db, db.connection:
            db.connection.execute('INSERT INTO run_control VALUES (?,?,?,?,?,?)',
                                  (old, 'running', (datetime.now(timezone.utc) - timedelta(days=9)).isoformat(), None, None, None))
        self.assertEqual(state_queries.close_stale('8d')['run_ids'], [old])
        with store.open() as db:
            state = db.connection.execute('SELECT state FROM run_control WHERE run_id=?', (old,)).fetchone()[0]
        self.assertEqual(state, 'cancelled')
        self.assertIn(state, recovery.TRANSITIONS)

    def test_close_stale_rejects_a_malformed_age(self):
        for value in ('7', '0d', '-1d', '7w', '99999d', ''):
            with self.assertRaises(ValueError, msg=value):
                state_queries.close_stale(value, dry_run=True)
