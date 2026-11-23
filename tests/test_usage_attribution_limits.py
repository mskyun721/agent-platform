"""Attribution bounds: candidate window and interval search (DBA F-1), retention (F-2, REVIEW N-4),
content lock scope (F-3), migration (F-4), session location (REVIEW N-1) and host detection (N-2)."""
import json
import os
import sqlite3
import time
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from test_observe_collect import codex_rows, jsonl
from test_usage_attribution import AttributionFixture, at, claude_rows, zulu

from agent_platform_mcp import events
from agent_platform_mcp.tools import observation, store, usage_attribution

SLO_SEC = 1.0


def synthetic_runs(state, count, now):
    """`count` ten-minute runs spread evenly over three years (DBA probe distribution)."""
    rows = []
    for index in range(count):
        start = now - timedelta(days=1095) + timedelta(seconds=index * 1095 * 86400 / count)
        backend = 'claude' if index % 3 else ('codex' if index % 2 else None)
        event = {'backend': backend, 'project_id': 'p1', 'collection_source': 'direct' if index % 2 else 'wrapper',
                 'payload': {'workspace': '/w', 'point': backend is None}}
        rows.append((str(uuid4()), json.dumps(event), 'p1', 't', start.isoformat(),
                     (start + timedelta(minutes=10)).isoformat(), 'completed'))
    state.connection.executemany('INSERT INTO runs VALUES (?,?,?,?,?,?,?)', rows)
    state.connection.commit()


def synthetic_turns(count, now):
    turns = []
    for index in range(count):
        start = now - timedelta(minutes=count - index)
        turns.append({'run_id': str(uuid4()), 'session_id': 's1', 'project_id': 'p1', 'workspace': '/w', 'backend': 'claude',
                      'ts': start.isoformat(), 'ended_at': (start + timedelta(seconds=30)).isoformat(), 'state': 'completed',
                      'usage': {'input_tokens': 1, 'output_tokens': 1, 'cache_read_tokens': 0, 'cache_write_tokens': 0}})
    return turns


def match_seconds(state, turns, now):
    """candidates() for the turns' window plus prepare() against an empty decision table."""
    content = sqlite3.connect(':memory:')
    content.executescript(usage_attribution.SCHEMA)
    began = time.perf_counter()
    runs = usage_attribution.candidates(state, usage_attribution.window(turns, now))
    plan = usage_attribution.prepare(content, turns, runs, now)
    return time.perf_counter() - began, runs, plan


class MatchPerformanceTest(unittest.TestCase):  # DBA F-1 regression: 100k runs x 500 turns
    def test_matching_stays_within_the_slo_at_three_years_of_runs(self):
        now = datetime.now(timezone.utc)
        with store.open() as state:  # the conftest copy's state.db
            synthetic_runs(state, 100_000, now)
            turns = synthetic_turns(500, now)
            elapsed, runs, plan = match_seconds(state, turns, now)
            loaded = len(usage_attribution.runs_of(runs))
            # the full-history decide() result is the same: the window only drops runs that cannot overlap
            full = usage_attribution.candidates(state)
            self.assertEqual([usage_attribution.decide(turn, full, now)[0] for turn in turns],
                             [row[6] for row in plan['rows']])
        self.assertLess(elapsed, SLO_SEC, f'matching took {elapsed:.3f}s')
        self.assertLess(loaded, 1000)  # about eight days of the 100k runs, not all of them

    def test_interval_search_matches_open_long_and_negative_runs(self):
        now = datetime(2026, 11, 23, 12, tzinfo=timezone.utc)
        def run(start, end):
            return {'run_id': str(uuid4()), 'source': 'direct', 'session': None,
                    'start': now + timedelta(minutes=start), 'end': None if end is None else now + timedelta(minutes=end)}
        group = [run(-600, 30), run(-5, -1), run(-120, None), run(5, 6), run(2, 1)]
        runs = {('claude', 'p1'): usage_attribution._group(group)}
        turn = {'run_id': 't', 'project_id': 'p1', 'workspace': '/w', 'backend': 'claude', 'usage': {'input_tokens': 1},
                'ts': now.isoformat(), 'ended_at': (now + timedelta(minutes=3)).isoformat()}
        expected = sorted(item['run_id'] for item in (group[0], group[2], group[4]))
        self.assertEqual(usage_attribution.decide(turn, runs, now + timedelta(hours=1))[2], expected)


class RetentionTest(AttributionFixture, unittest.TestCase):  # DBA F-2, REVIEW N-4
    def test_suppressed_turn_is_not_attributed_again(self):
        run = self.start('pay', '00:00:00', '00:10:00')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        self.collect()
        with self.view.content_db() as db:
            db.execute('UPDATE native_runs SET expires=0')
        with unittest.mock.patch.object(self.native, 'PARSER_VERSION', self.native.PARSER_VERSION + 1):
            result = self.collect()
        with self.view.content_db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM native_attribution').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM native_runs').fetchone()[0], 0)
        self.assertEqual(result['claude']['attribution']['attributed'], 0)
        self.assertEqual(self.usage(run)['input_tokens'], 10)  # a written sum stays (ADR-012)

    def test_cleanup_removes_decisions_that_outlived_their_turn(self):
        self.start('pay', '00:00:00', '00:10:00')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        self.collect()
        with self.view.content_db() as db:  # an orphan row as left by the pre-fix collector
            db.execute("INSERT INTO native_attribution VALUES ('gone','test-project','/w','claude','s1',NULL,"
                       "'unattributed',NULL,'[]','{}')")
        with self.view.content_db() as db:
            self.assertEqual([row[0] for row in db.execute('SELECT turn_id FROM native_attribution')],
                             [row[0] for row in db.execute('SELECT run_id FROM native_runs')])


class LockScopeTest(AttributionFixture, unittest.TestCase):  # DBA F-3
    def other_writer_wait(self):
        """Seconds another writer waits for the content DB write lock (timeout 0: a held lock fails at once)."""
        other = sqlite3.connect(store.default_path().parent / 'llm-content.db', timeout=0, isolation_level=None)
        began = time.perf_counter()
        try:
            other.execute('BEGIN IMMEDIATE')
            other.execute('ROLLBACK')
        finally:
            other.close()
        return time.perf_counter() - began

    def test_decisions_and_state_writes_run_without_the_content_write_lock(self):
        run = self.start('pay', '00:00:00', '00:10:00')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        waits = []
        prepare, attributed = usage_attribution.prepare, store.Store.attributed_usage
        def slow_prepare(*args, **kwargs):
            time.sleep(0.2)  # a slow decision pass must not hold the lock
            waits.append(self.other_writer_wait())
            return prepare(*args, **kwargs)
        def checked_state_write(state, usages):
            waits.append(self.other_writer_wait())
            return attributed(state, usages)
        with unittest.mock.patch.object(usage_attribution, 'prepare', slow_prepare), \
                unittest.mock.patch.object(store.Store, 'attributed_usage', checked_state_write):
            self.collect()
        self.assertEqual(len(waits), 2)
        self.assertTrue(all(wait < 0.1 for wait in waits), waits)
        self.assertEqual(self.usage(run)['input_tokens'], 10)

    def test_runs_of_one_file_are_written_in_one_state_transaction(self):
        first = self.start('pay', '00:00:00', '00:02:30')
        second = self.start('pay', '00:03:30', '00:10:00')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00')
                   + claude_rows(str(self.root), 'u2', '00:04:00', '00:05:00'))
        calls = []
        attributed = store.Store.attributed_usage
        def counted(state, usages):
            calls.append(sorted(usages))
            return attributed(state, usages)
        with unittest.mock.patch.object(store.Store, 'attributed_usage', counted):
            self.assertEqual(self.collect()['claude']['attribution']['runs_updated'], 2)
        self.assertEqual(calls, [sorted([first, second])])


class MigrationTest(AttributionFixture, unittest.TestCase):  # DBA F-4
    def test_pre_session_table_is_dropped_once_and_recreated(self):
        with self.view.content_db() as db:
            db.execute('DROP TABLE native_attribution')
            db.execute('CREATE TABLE native_attribution (turn_id TEXT PRIMARY KEY, project_id TEXT, workspace TEXT NOT NULL, '
                       'backend TEXT NOT NULL, ts TEXT, status TEXT NOT NULL, run_id TEXT, candidates_json TEXT NOT NULL, '
                       'usage_json TEXT NOT NULL)')
        path = store.default_path().parent / 'llm-content.db'
        first, second = sqlite3.connect(path), sqlite3.connect(path)
        try:
            usage_attribution.migrate(first)
            usage_attribution.migrate(second)  # the other process finds nothing left to drop
        finally:
            first.close()
            second.close()
        with self.view.content_db() as db:
            self.assertIn('session_id', {row[1] for row in db.execute('PRAGMA table_info(native_attribution)')})


def codex_turn(cwd, session, begin, end):
    rows = codex_rows(cwd, session, 't1', 'codex prompt')
    for row in rows:
        if 'timestamp' in row:
            row['timestamp'] = zulu(begin if row['payload']['type'] == 'task_started' else end)
    return rows


class SessionLocationTest(AttributionFixture, unittest.TestCase):  # REVIEW N-1
    def start_from(self, pwd, env=None):
        environment = {'CODEX_SANDBOX': 'seatbelt', **(env or {})}
        if pwd is not None:
            environment['PWD'] = pwd
        with unittest.mock.patch.object(Path, 'cwd', return_value=Path(self.platform) / 'mcp-server'), \
                unittest.mock.patch.dict(os.environ, environment), \
                unittest.mock.patch.object(observation, '_now', return_value=at('00:00:00')):
            if pwd is None:
                os.environ.pop('PWD', None)
            started = observation.run_start('pay', 'backend', root='test-project')
        with store.open() as db:
            run = db.run(started['run_id'])
            db.record_event(events.RunEvent(str(uuid4()), run['run_id'], None, run['project_id'], run['task_id'], run['role'],
                                            'run_ended', at('00:10:00'), run['backend'], None, {}, {'outcome': 'completed'},
                                            'direct', 'partial'))
        return run

    def test_target_shell_through_the_uv_alias_is_the_target_session(self):  # probe J
        run = self.start_from(str(self.root))
        self.assertEqual((run['backend'], run['payload']['session_workspace']), ('codex', str(Path(self.root).resolve())))
        self.view.configure(self.platform, True)
        jsonl(self.codex / 'other.jsonl', codex_turn(self.platform, 'other', '00:03:00', '00:04:00'))
        self.collect()
        self.assertEqual(self.usage(run['run_id'])['completeness'], 'unavailable')  # not the platform session's 20

    def test_shell_below_the_platform_root_is_the_platform_session(self):
        run = self.start_from(str(Path(self.platform) / 'docs'))
        self.assertEqual(run['payload']['session_workspace'], self.platform)

    def test_unknown_shell_location_is_not_recorded(self):
        for pwd in (None, 'relative/dir', '/no/such/dir'):
            with self.subTest(pwd=pwd):
                self.assertNotIn('session_workspace', self.start_from(pwd)['payload'])


class HostDetectionTest(unittest.TestCase):  # REVIEW N-2
    def detect(self, env):
        with unittest.mock.patch.dict(os.environ, env):
            backend = observation.host_backend()
            return backend, observation.session_identity(backend).get('source_session_id')

    def test_only_confirmed_variables_detect_a_host(self):
        cases = {'user CODEX_API_KEY': ({'CODEX_API_KEY': 'x'}, ('unknown', None)),
                 'CODEX_HOME': ({'CODEX_HOME': '/x'}, ('unknown', None)),
                 'codex sandbox': ({'CODEX_SANDBOX': 'seatbelt', 'CODEX_THREAD_ID': 'th-1'}, ('codex', 'th-1')),
                 'codex thread only': ({'CODEX_THREAD_ID': 'th-2'}, ('codex', 'th-2')),
                 'claude': ({'CLAUDECODE': '1', 'CLAUDE_CODE_SESSION_ID': 'c-1'}, ('claude', 'c-1'))}
        for name, (env, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.detect(env), expected)

    def test_nested_hosts_are_unknown_without_an_inherited_session(self):
        env = {'CLAUDECODE': '1', 'CLAUDE_CODE_SESSION_ID': 'parent', 'CODEX_SANDBOX': 'seatbelt', 'CODEX_THREAD_ID': 'th'}
        self.assertEqual(self.detect(env), ('unknown', None))
        with unittest.mock.patch.dict(os.environ, env):  # an explicit backend does not take the inherited id either
            self.assertNotIn('source_session_id', observation.session_identity('claude'))


if __name__ == '__main__':
    unittest.main()
