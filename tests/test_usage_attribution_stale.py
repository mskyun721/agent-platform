"""Stale open runs (DBA F-7), state.db errors per file (REVIEW N-6), pending sums (N-7, DBA F-10), distinct
runs_updated and the human-run `state close-stale` (DBA F-9, F-11, REVIEW N-9..N-12)."""
import json
import os
import time
import socket
import sqlite3
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from test_usage_attribution import AttributionFixture, at, claude_rows
from test_usage_attribution_limits import SLO_SEC, match_seconds, synthetic_runs, synthetic_turns

from agent_platform_mcp import events
from agent_platform_mcp.tools import llm_view, recovery, state_queries, store, usage_attribution


def full_events(state, run_ids):
    """Gives synthetic runs a complete run_started event so `state close-stale` can end them."""
    rows = []
    for run_id, raw, started in state.connection.execute(
            f"SELECT run_id,event_json,started_at FROM runs WHERE run_id IN ({','.join('?' * len(run_ids))})", run_ids).fetchall():
        old = json.loads(raw)
        rows.append((json.dumps({'event_id': str(uuid4()), 'run_id': run_id, 'parent_run_id': None, 'project_id': 'p1', 'task_id': 'old',
                                 'role': 'backend', 'event_type': 'run_started', 'ts': started, 'backend': old['backend'], 'model': 'm',
                                 'skill_versions': {}, 'payload': old['payload'], 'collection_source': old['collection_source'],
                                 'completeness': 'partial', 'schema_version': 1}), run_id))
    state.connection.executemany("UPDATE runs SET event_json=?,task_id='old' WHERE run_id=?", rows)
    state.connection.commit()


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
    full_events(state, chosen)
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

    def test_close_stale_keeps_the_baseline_decisions_and_the_slo(self):  # DBA F-9 regression
        now = datetime.now(timezone.utc)
        turns = synthetic_turns(500, now)
        with store.open() as state:
            synthetic_runs(state, 100_000, now)
            _, _, baseline = match_seconds(state, turns, now)
            opened = open_stale(state, now, 0.05)
            began = time.perf_counter()
            result = state_queries.close_stale('7d')
            closing = time.perf_counter() - began
            elapsed, runs, plan = match_seconds(state, turns, now)
            ended = state.connection.execute("SELECT max(ended_at) FROM runs WHERE outcome='abandoned'").fetchone()[0]
            stale = usage_attribution.stale_open(state, now)
        print(f'\nclose-stale {result["closed"]} runs in {closing:.2f}s; matching after it {elapsed:.3f}s')
        self.assertEqual((result['closed'], stale), (opened, 0))
        self.assertLess(ended, (now - usage_attribution.MAX_OPEN).isoformat())  # the last activity, not now
        self.assertLessEqual(elapsed, SLO_SEC, f'matching took {elapsed:.3f}s')
        self.assertLess(len(usage_attribution.runs_of(runs)), 1000)
        self.assertEqual([row[6] for row in plan['rows']], [row[6] for row in baseline['rows']])

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
        self.assertEqual((result['claude']['imported'], result['claude']['errors'], result['claude']['state_pending_files']), (1, 0, 1))  # N-18
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
        for value in ('7', '0d', '-1d', '7w', '99999d', '', '1h', '23h'):
            with self.assertRaises(ValueError, msg=value):
                state_queries.close_stale(value, dry_run=True)

    def test_abandoned_run_is_no_candidate_and_ends_at_its_last_activity(self):  # DBA F-9 (probe_close)
        stale = [self.started(days=10 + index) for index in range(3)]
        real = self.start('pay', '00:00:00', '00:30:00')
        turn = {'run_id': 't1', 'project_id': 'test-project', 'workspace': str(self.root), 'backend': 'claude', 'session_id': 's1',
                'usage': {'input_tokens': 1}, 'ts': at('00:05:00'), 'ended_at': at('00:06:00')}
        self.assertEqual(state_queries.close_stale('7d')['closed'], 3)
        now = datetime.now(timezone.utc)
        with store.open() as db:
            runs = usage_attribution.candidates(db, usage_attribution.window([turn], now))
            self.assertEqual(usage_attribution.decide(turn, runs, now)[:2], ('attributed', real))
            self.assertEqual(db.run(stale[0])['ended_at'], db.run(stale[0])['ts'])
            db.connection.execute("UPDATE runs SET ended_at=? WHERE run_id=?", (now.isoformat(), stale[0]))  # closed by b2ba7b1
            db.connection.commit()
            self.assertNotIn(stale[0], usage_attribution.runs_of(usage_attribution.candidates(db, usage_attribution.window([turn], now))))

    def test_resumable_and_checkpointed_runs_are_kept_and_listed(self):  # REVIEW N-9 (probe R)
        paused, kept, gone = self.started(days=10), self.started(days=10), self.started(days=10)
        old = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
        with store.open() as db, db.connection:
            db.connection.execute('INSERT INTO run_control VALUES (?,?,?,?,?,?)', (paused, 'interrupted', old, None, None, 'paused'))
            db.connection.execute('INSERT INTO checkpoints VALUES (?,?,?)', (kept, 1, '{}'))
        preview = state_queries.close_stale('7d', dry_run=True)
        by_id = {item['run_id']: item for item in preview['runs']}
        self.assertEqual((by_id[paused]['action'], by_id[paused]['reason'], by_id[paused]['recovery_state']), ('skip', 'resumable', 'interrupted'))
        self.assertEqual(by_id[kept]['reason'], 'checkpoint')
        self.assertEqual((by_id[gone]['action'], by_id[gone]['recovery_state'], by_id[gone]['role'], by_id[gone]['backend']),
                         ('close', 'none', 'backend', 'claude'))
        self.assertEqual(set(by_id[gone]), {'run_id', 'role', 'backend', 'started_at', 'last_activity', 'recovery_state', 'action', 'outcome', 'reason'})
        self.assertEqual(state_queries.close_stale('7d')['run_ids'], [gone])
        with store.open() as db:
            self.assertEqual(recovery._state(db, paused)['state'], 'interrupted')
            self.assertIsNone(db.run(kept)['ended_at'])

    def test_closed_run_without_a_control_row_is_cancelled(self):  # REVIEW N-10 (probe S)
        run, legacy = self.started(days=10), self.started(days=10)
        state_queries.close_stale('7d')
        with store.open() as db, db.connection:
            self.assertEqual(db.connection.execute('SELECT state FROM run_control WHERE run_id=?', (run,)).fetchone()[0], 'cancelled')
            db.connection.execute('DELETE FROM run_control WHERE run_id=?', (legacy,))  # closed before the row was written
        for run_id in (run, legacy):
            with store.open() as db:
                self.assertEqual((recovery._state(db, run_id)['state'], db.run(run_id)['state']), ('cancelled', 'cancelled'))
            self.assertEqual(recovery.transition(run_id, 'cancelled')['state'], 'cancelled')
            with self.assertRaisesRegex(ValueError, 'invalid transition cancelled to running'):
                recovery.transition(run_id, 'running')
            self.assertEqual(recovery.resume(run_id)['verdict'], 'done')
            with self.assertRaisesRegex(ValueError, 'terminal'):
                recovery.checkpoint(run_id, 'p', 'n')

    def test_recent_event_keeps_a_run_without_a_control_row(self):  # REVIEW N-11 (probe T)
        active, idle = self.started(days=2), self.started(days=2)
        with store.open() as db, db.connection:
            db.connection.execute('INSERT INTO events VALUES (?,?,?,?,?)',
                                  (str(uuid4()), active, 'handoff', (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), '{}'))
        result = state_queries.close_stale('1d', dry_run=True)
        self.assertEqual((result['run_ids'], result['skipped']), ([idle], {'recent activity': 1}))

    def test_run_ended_meanwhile_is_skipped(self):  # REVIEW N-11: per-run transactions tolerate a concurrent state end
        first, second = self.started(days=11), self.started(days=10)
        original = state_queries._close
        def end_second_too(db, item):
            original(db, item)
            db.connection.execute("UPDATE runs SET ended_at=?,outcome='completed' WHERE run_id=?", (recovery.now(), second))
        with unittest.mock.patch.object(state_queries, '_close', side_effect=end_second_too):
            result = state_queries.close_stale('7d')
        self.assertEqual((result['run_ids'], result['skipped']), ([first], {'already ended': 1}))

    def test_close_stale_covers_the_stale_open_runs_population(self):  # DBA F-11, REVIEW N-12 (probe V)
        self.started(days=10)
        point = self.started(days=10, backend=None)
        with store.open() as db:
            stale = usage_attribution.stale_open(db, datetime.now(timezone.utc))
        result = state_queries.close_stale('7d')
        self.assertEqual((stale, result['stale_runs'], result['closed']), (1, 1, 1))
        with store.open() as db:
            self.assertIsNone(db.run(point)['ended_at'])


class ResyncIsolationTest(StaleFixture, unittest.TestCase):  # DBA F-10
    def test_a_failing_pending_run_does_not_block_other_files(self):
        stuck = self.start('pay', '00:00:00', '00:10:00')
        with self.view.content_db() as db:
            db.execute('INSERT INTO native_pending VALUES (?)', (stuck,))
            db.commit()
        other = self.start('pay', '00:20:00', '00:30:00')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:21:00', '00:22:00'))
        original = store.Store.attributed_usage
        def fail_stuck(self_, usages):
            if stuck in usages:
                raise ValueError('permanent')
            return original(self_, usages)
        with unittest.mock.patch.object(store.Store, 'attributed_usage', autospec=True, side_effect=fail_stuck):
            result = self.collect()
        self.assertEqual((result['resync_error'], result['claude']['attribution']['attributed']), ('ValueError', 1))
        self.assertNotIn('attribution_skipped', result)
        self.assertEqual(self.usage(other)['input_tokens'], 10)
        with self.view.content_db() as db:
            self.assertEqual([row[0] for row in db.execute('SELECT run_id FROM native_pending')], [stuck])
            self.assertEqual(db.execute('SELECT count(*) FROM native_files').fetchone()[0], 1)
        self.assertNotIn('resync_error', self.collect())
