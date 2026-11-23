"""Native session usage attribution to runs (TASK Phase 4, PRD BR-2/AC-2) and point-run marker (REVIEW L-4)."""
import json
import os
import time
import unittest
import unittest.mock
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from test_observe_collect import CollectFixture, codex_rows, jsonl

from agent_platform_mcp import events
from agent_platform_mcp.tools import observation, projects, store, usage_attribution, usage_report

DAY = '2026-11-23T'


def at(clock):
    return f'{DAY}{clock}+00:00'


def zulu(clock):
    return f'{DAY}{clock}Z'  # transcripts write UTC with a Z suffix


def claude_rows(cwd, uuid, start, end, messages=((10, 2, 3, 4),), sidechain=False, session='s1'):
    """One user turn from `start` to `end` with one assistant API message per usage tuple."""
    flags = {'isSidechain': True, 'agentId': 'a1'} if sidechain else {}
    rows = [{'type': 'user', 'uuid': uuid, 'sessionId': session, 'cwd': cwd, 'timestamp': zulu(start),
             'message': {'content': 'prompt ' + uuid}, **flags}]
    for index, (i, o, r, w) in enumerate(messages):
        last = index == len(messages) - 1
        rows.append({'type': 'assistant', 'timestamp': zulu(end if last else start), 'cwd': cwd, **flags,
                     'message': {'id': f'm-{uuid}-{index}', 'model': 'claude-test', 'stop_reason': 'end_turn' if last else None,
                                 'content': [{'type': 'text', 'text': 'answer'}],
                                 'usage': {'input_tokens': i, 'output_tokens': o, 'cache_read_input_tokens': r,
                                           'cache_creation_input_tokens': w}}})
    return rows


class AttributionFixture(CollectFixture):
    def setUp(self):
        super().setUp()
        self.view.configure('test-project', True)
        self.context = projects.resolve('test-project')

    def start(self, task, begin, end=None, backend='claude', source='direct', role='backend', usage=None, **payload):
        event = events.RunEvent(str(uuid4()), str(uuid4()), None, 'test-project', task, role, 'run_started', at(begin),
                                backend, 'm', {}, {'workspace': str(self.root), **payload}, source, 'partial')
        with store.open() as db:
            db.record_event(event)
            db.record_usage(event.run_id, usage or events.Usage(None, None, None, None, 'unavailable', 'unavailable'))
            if end:
                db.record_event(replace(event, event_id=str(uuid4()), event_type='run_ended', ts=at(end),
                                        payload={'outcome': 'completed'}))
        return event.run_id

    def usage(self, run_id):
        with store.open() as db:
            row = db.connection.execute('SELECT payload_json FROM usage WHERE run_id=?', (run_id,)).fetchone()
        return json.loads(row[0])

    def collect(self):
        result = self.native.collect_once('test-project')
        self.assertEqual(result['status'], 'collected', result)
        return result

    def write(self, name, rows):
        path = self.claude / 'proj' / name
        jsonl(path, rows)
        return path


class SingleOverlapTest(AttributionFixture, unittest.TestCase):
    def test_turn_inside_one_direct_run_is_attributed_and_reported(self):
        run = self.start('pay', '00:00:00', '00:10:00')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))

        result = self.collect()

        self.assertEqual(result['claude']['attribution'], {'attributed': 1, 'ambiguous': 0, 'unattributed': 0,
                                                           'measured_elsewhere': 0, 'no_usage': 0, 'runs_updated': 1,
                                                           'ambiguous_sessions': 0})
        usage = self.usage(run)
        self.assertEqual((usage['input_tokens'], usage['output_tokens'], usage['cache_read_tokens'], usage['cache_write_tokens']),
                         (10, 2, 3, 4))
        self.assertEqual((usage['source'], usage['completeness']), (usage_attribution.SOURCE, 'full'))
        report = usage_report.feature_usage(self.context, 'features/pay')
        self.assertTrue(report['complete'])
        self.assertEqual(report['total']['input_tokens'], 10)
        self.assertEqual((report['unattributed_runs'], report['ambiguous_runs']), (0, 0))

    def test_turn_that_starts_before_the_run_but_overlaps_it_is_attributed(self):
        """A direct session's `state start` runs inside the turn that asked for the role."""
        run = self.start('pay', '00:01:30', '00:01:50')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        self.collect()
        self.assertEqual(self.usage(run)['input_tokens'], 10)

    def test_open_run_covers_turns_until_now(self):
        run = self.start('pay', '00:00:00')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        self.collect()
        self.assertEqual(self.usage(run)['input_tokens'], 10)

    def test_backend_and_project_must_match(self):
        claude_run = self.start('pay', '00:00:00', '00:10:00')
        rows = codex_rows(str(self.root), 'c1', 't1', 'codex prompt')
        for row in rows:
            if 'timestamp' in row:
                row['timestamp'] = zulu('00:01:00' if row['payload']['type'] == 'task_started' else '00:02:00')
        jsonl(self.codex / 'r1.jsonl', rows)
        result = self.collect()
        self.assertEqual(result['codex']['attribution']['unattributed'], 1)
        self.assertEqual(self.usage(claude_run)['completeness'], 'unavailable')

    def test_codex_turn_without_cache_write_count_is_full_when_input_output_known(self):
        run = self.start('pay', '00:00:00', '00:10:00', backend='codex')
        rows = codex_rows(str(self.root), 'c1', 't1', 'codex prompt')
        for row in rows:
            if 'timestamp' in row:
                row['timestamp'] = zulu('00:01:00' if row['payload']['type'] == 'task_started' else '00:02:00')
            if row['type'] == 'token_usage_record':
                del row['payload']['turn_token_usage']['cache_write_input_tokens']
        jsonl(self.codex / 'r1.jsonl', rows)
        self.collect()
        usage = self.usage(run)
        self.assertEqual((usage['input_tokens'], usage['output_tokens'], usage['cache_write_tokens'], usage['completeness']),
                         (20, 5, None, 'full'))


class AmbiguousAndNoneTest(AttributionFixture, unittest.TestCase):
    def test_two_overlapping_runs_are_ambiguous_and_never_split(self):
        first = self.start('pay', '00:00:00', '00:10:00')
        second = self.start('ship', '00:00:30', '00:05:00', role='reviewer')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))

        result = self.collect()

        self.assertEqual(result['claude']['attribution']['ambiguous'], 1)
        for run in (first, second):
            self.assertEqual(self.usage(run)['completeness'], 'unavailable')
        for feature in ('features/pay', 'features/ship'):
            self.assertEqual(usage_report.feature_usage(self.context, feature)['ambiguous_runs'], 1)
        self.assertEqual(usage_report.type_stats(self.context)['ambiguous_runs'], 1)

    def test_turn_without_an_overlapping_run_is_unattributed(self):
        self.start('pay', '00:00:00', '00:01:00')
        self.start('pay', '00:10:00', '00:11:00')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:05:00', '00:06:00'))
        self.write('s2.jsonl', claude_rows(str(self.root), 'u2', '02:00:00', '02:01:00', session='s2'))

        result = self.collect()

        self.assertEqual(result['claude']['attribution']['unattributed'], 2)
        feature = usage_report.feature_usage(self.context, 'features/pay')
        self.assertEqual((feature['unattributed_runs'], feature['ambiguous_runs']), (1, 0))  # inside the feature's span only
        self.assertEqual(usage_report.type_stats(self.context)['unattributed_runs'], 2)
        self.assertEqual(usage_report.group_stats(self.context, 'role')['unattributed_runs'], 2)
        self.assertEqual(usage_report.type_stats(self.context, since='2026-11-24')['unattributed_runs'], 0)

    def test_wrapper_run_keeps_its_own_usage(self):
        measured = events.Usage(500, 50, 0, 0, 'wrapper-fixture', 'full')
        wrapper = self.start('pay', '00:00:00', '00:10:00', source='wrapper', usage=measured)
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        result = self.collect()
        self.assertEqual(result['claude']['attribution']['measured_elsewhere'], 1)
        self.assertEqual(self.usage(wrapper)['input_tokens'], 500)

    def test_recorded_non_placeholder_usage_is_not_replaced(self):
        run = self.start('pay', '00:00:00', '00:10:00', usage=events.Usage(7, 1, None, None, 'manual', 'full'))
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        result = self.collect()
        self.assertEqual(result['claude']['attribution']['runs_updated'], 0)
        self.assertEqual(self.usage(run)['input_tokens'], 7)

    def test_no_collector_data_reports_null(self):
        context = projects.ProjectContext('elsewhere', self.root / 'none')
        self.assertEqual(usage_attribution.project_counts(context, None),
                         {'unattributed_runs': 0, 'ambiguous_runs': 0})
        with unittest.mock.patch.object(usage_attribution, '_content_path', return_value=self.root / 'missing.db'):
            self.assertEqual(usage_attribution.project_counts(self.context, None),
                             {'unattributed_runs': None, 'ambiguous_runs': None})


class SubagentAndIdempotenceTest(AttributionFixture, unittest.TestCase):
    def test_subagent_turns_add_to_the_run(self):
        run = self.start('pay', '00:00:00', '00:10:00')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:05:00'))
        sub = self.claude / 'proj' / 's1' / 'subagents' / 'agent-a1.jsonl'
        jsonl(sub, claude_rows(str(self.root), 'sub1', '00:02:00', '00:03:00', messages=((100, 20, 30, 40),), sidechain=True))

        result = self.collect()

        self.assertEqual(result['claude']['subagent_turns'], 1)
        self.assertEqual(result['claude']['attribution']['attributed'], 2)
        usage = self.usage(run)
        self.assertEqual((usage['input_tokens'], usage['output_tokens'], usage['cache_read_tokens'], usage['cache_write_tokens']),
                         (110, 22, 33, 44))

    def test_recollecting_never_double_counts(self):
        run = self.start('pay', '00:00:00', '00:10:00')
        path = self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        self.collect()
        self.assertEqual(self.collect()['claude']['unchanged_files'], 1)
        with unittest.mock.patch.object(self.native, 'PARSER_VERSION', self.native.PARSER_VERSION + 1):
            self.collect()  # forced reparse of the same turn
        self.assertEqual(self.usage(run)['input_tokens'], 10)
        # The turn grows while in progress: the sum is recomputed, not added to.
        jsonl(path, claude_rows(str(self.root), 'u1', '00:01:00', '00:03:00', messages=((10, 2, 3, 4), (5, 1, 1, 1))))
        self.collect()
        self.assertEqual(self.usage(run)['input_tokens'], 15)
        with store.open() as db:
            self.assertEqual(db.connection.execute('SELECT COUNT(*) FROM usage WHERE run_id=?', (run,)).fetchone()[0], 1)

    def test_turn_that_becomes_ambiguous_restores_the_placeholder(self):
        first = self.start('pay', '00:00:00', '00:10:00')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        self.collect()
        self.assertEqual(self.usage(first)['input_tokens'], 10)
        self.start('ship', '00:01:30', '00:01:40', role='reviewer')
        with unittest.mock.patch.object(self.native, 'PARSER_VERSION', self.native.PARSER_VERSION + 1):
            self.collect()
        self.assertEqual((self.usage(first)['completeness'], self.usage(first)['input_tokens']), ('unavailable', None))


class PointRunTest(AttributionFixture, unittest.TestCase):  # REVIEW L-4
    def test_point_run_with_failed_event_is_not_an_llm_run(self):
        result = observation.point({'feature': 'sample-task', 'passed': True}, self.context, 'orchestrator', 'handoff',
                                   {'unsupported_raw_field': 'x'})
        self.assertFalse(result['observability']['stored'])
        with store.open() as db:
            run = db.run(result['run_id'])
        self.assertEqual((run['payload']['point'], run['outcome']), ('handoff', 'failed'))
        report = usage_report.feature_usage(self.context, 'features/sample-task')
        self.assertEqual(report['runs'], 0)

    def test_verification_point_run_is_marked(self):
        started = observation.start_context('pay', 'qa', None, self.context, point='verification')
        with store.open() as db:
            self.assertEqual(db.run(started['run_id'])['payload']['point'], 'verification')
        with self.assertRaises(ValueError):
            observation.start_context('pay', 'qa', None, self.context, point='usage')



def user(cwd, uuid, clock, prompt, session='s1'):
    return {'type': 'user', 'uuid': uuid, 'sessionId': session, 'cwd': cwd, 'timestamp': zulu(clock), 'message': {'content': prompt}}


class OpenTurnTest(AttributionFixture, unittest.TestCase):  # REVIEW H-1, L-6
    def test_interrupted_turn_ends_at_its_last_activity_not_now(self):
        rows = [user(str(self.root), 'u1', '00:01:00', 'early prompt'),
                {'type': 'assistant', 'timestamp': zulu('00:01:10'), 'cwd': str(self.root),
                 'message': {'id': 'm-u1', 'model': 'x', 'stop_reason': 'tool_use', 'content': [{'type': 'text', 'text': 'a'}],
                             'usage': {'input_tokens': 1000, 'output_tokens': 1, 'cache_read_input_tokens': 0,
                                       'cache_creation_input_tokens': 0}}}]
        self.write('s1.jsonl', rows + claude_rows(str(self.root), 'u2', '00:03:00', '00:04:00'))
        run = self.start('later', '00:10:00', '00:12:00')
        result = self.collect()
        self.assertEqual((result['claude']['attribution']['unattributed'], result['claude']['attribution']['attributed']), (2, 0))
        self.assertEqual(self.usage(run)['completeness'], 'unavailable')

    def test_last_turn_is_open_only_while_its_file_is_fresh(self):
        rows = [user(str(self.root), 'u1', '00:01:00', 'still running'),
                {'type': 'assistant', 'timestamp': zulu('00:01:10'), 'cwd': str(self.root),
                 'message': {'id': 'm-u1', 'model': 'x', 'stop_reason': 'tool_use', 'content': [],
                             'usage': {'input_tokens': 7, 'output_tokens': 1}}}]
        path = self.write('s1.jsonl', rows)
        run = self.start('pay', '00:05:00')
        self.collect()
        self.assertEqual(self.usage(run)['input_tokens'], 7)  # a fresh file: the turn may still be running
        stale = time.time() - 3600
        os.utime(path, (stale, stale))
        self.collect()
        self.assertEqual(self.usage(run)['completeness'], 'unavailable')

    def test_reply_less_command_turn_never_downgrades_the_sum(self):
        rows = [user(str(self.root), 'c1', '00:00:30', '<command-name>/model</command-name>')]
        self.write('s1.jsonl', rows + claude_rows(str(self.root), 'u5', '00:05:00', '00:06:00'))
        run = self.start('pay', '00:00:00', '00:07:00')
        result = self.collect()
        self.assertEqual((result['claude']['attribution']['no_usage'], result['claude']['attribution']['attributed']), (1, 1))
        self.assertEqual((self.usage(run)['input_tokens'], self.usage(run)['completeness']), (10, 'full'))


class SessionMatchTest(AttributionFixture, unittest.TestCase):  # REVIEW M-1, M-2, M-3, L-6
    def test_other_session_turns_make_a_session_less_run_ambiguous(self):
        run = self.start('pay', '00:00:00', '00:10:00')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00', session='s1'))
        self.write('s2.jsonl', claude_rows(str(self.root), 'v1', '00:03:00', '00:04:00', session='other-session'))
        result = self.collect()
        self.assertEqual(result['claude']['attribution']['ambiguous_sessions'], 2)
        # counted after the ambiguity pass: the first session's turn is no longer reported as attributed
        self.assertEqual((result['claude']['attribution']['attributed'], result['claude']['attribution']['ambiguous']), (0, 2))
        self.assertEqual(self.usage(run)['completeness'], 'unavailable')  # never 10 + 10
        self.assertEqual(usage_report.feature_usage(self.context, 'features/pay')['ambiguous_runs'], 2)
        with self.view.content_db() as db:
            self.assertEqual({row[0] for row in db.execute('SELECT status FROM native_attribution')}, {'ambiguous'})

    def test_run_with_a_session_id_takes_only_that_session(self):
        run = self.start('pay', '00:00:00', '00:10:00', source_session_id='s1')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00', session='s1'))
        self.write('s2.jsonl', claude_rows(str(self.root), 'v1', '00:03:00', '00:04:00', session='other-session'))
        self.collect()
        self.assertEqual(self.usage(run)['input_tokens'], 10)

    def test_platform_root_session_attributes_to_the_target_run(self):
        self.view.configure(self.platform, True)
        with unittest.mock.patch.dict(os.environ, {'CLAUDECODE': '1', 'CLAUDE_CODE_SESSION_ID': 's9', 'PWD': self.platform}), \
                unittest.mock.patch.object(Path, 'cwd', return_value=Path(self.platform) / 'mcp-server'), \
                unittest.mock.patch.object(observation, '_now', return_value=at('00:00:00')):
            started = observation.run_start('pay', 'backend', root='test-project')
        with store.open() as db:
            run = db.run(started['run_id'])
        self.assertEqual((run['backend'], run['payload']['session_workspace'], run['payload']['source_session_id']),
                         ('claude', self.platform, 's9'))
        jsonl(self.claude / 'plat' / 's9.jsonl', claude_rows(self.platform, 'p1', '00:01:00', '00:02:00', session='s9'))
        jsonl(self.claude / 'plat' / 's8.jsonl', claude_rows(self.platform, 'p2', '00:01:00', '00:02:00', session='s8'))
        self.collect()
        self.assertEqual(self.usage(started['run_id'])['input_tokens'], 10)

    def test_unknown_backend_run_needs_turns_of_one_backend(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            self.assertEqual(observation.host_backend(), 'unknown')
        run = self.start('pay', '00:00:00', '00:10:00', backend='unknown')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        self.collect()
        self.assertEqual(self.usage(run)['input_tokens'], 10)
        rows = codex_rows(str(self.root), 'c1', 't1', 'codex prompt')
        for row in rows:
            if 'timestamp' in row:
                row['timestamp'] = zulu('00:03:00' if row['payload']['type'] == 'task_started' else '00:04:00')
        jsonl(self.codex / 'r1.jsonl', rows)
        self.collect()
        self.assertEqual(self.usage(run)['completeness'], 'unavailable')


class StateUnavailableTest(AttributionFixture, unittest.TestCase):  # REVIEW M-4, L-4, L-6
    def test_turns_are_collected_when_state_db_cannot_open_and_attribution_retries(self):
        run = self.start('pay', '00:00:00', '00:10:00')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        with unittest.mock.patch.object(store, 'open', side_effect=store.StoreError('state storage unavailable')):
            result = self.collect()
        self.assertEqual(result['claude']['imported'], 1)
        self.assertTrue(result['attribution_skipped'].startswith('state unavailable'))
        self.assertEqual(len(self.stored()), 1)
        self.collect()  # the file stayed unsigned
        self.assertEqual(self.usage(run)['input_tokens'], 10)

    def test_observability_off_collects_without_touching_state(self):
        run = self.start('pay', '00:00:00', '00:10:00')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        with unittest.mock.patch.object(observation, '_enabled', return_value=False), \
                unittest.mock.patch.object(store, 'open', side_effect=AssertionError('must not open state.db')):
            result = self.collect()
        self.assertEqual((result['claude']['imported'], result['attribution_skipped']), (1, 'observability disabled'))
        self.assertEqual(self.usage(run)['completeness'], 'unavailable')

    def test_state_write_failure_leaves_the_file_unsigned_and_converges(self):  # DBA F-3, F-6
        run = self.start('pay', '00:00:00', '00:10:00')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        with unittest.mock.patch.object(store.Store, 'attributed_usage', side_effect=store.StoreError('x')):
            self.assertEqual(self.collect()['claude']['errors'], 1)
        with self.view.content_db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM native_files').fetchone()[0], 0)
        self.assertEqual(self.usage(run)['completeness'], 'unavailable')
        self.collect()
        self.assertEqual(self.usage(run)['input_tokens'], 10)

    def test_imported_snapshot_replaces_an_attribution(self):
        run = self.start('pay', '00:00:00', '00:10:00')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        self.collect()
        with store.open() as db:
            db.record_usage(run, events.Usage(99, 9, None, None, 'imported-fixture', 'partial'))
        with unittest.mock.patch.object(self.native, 'PARSER_VERSION', self.native.PARSER_VERSION + 1):
            self.collect()
        self.assertEqual((self.usage(run)['input_tokens'], self.usage(run)['source']), (99, 'imported-fixture'))

    def test_decisions_expire_with_their_turn(self):
        self.start('pay', '00:00:00', '00:10:00')
        self.write('s1.jsonl', claude_rows(str(self.root), 'u1', '00:01:00', '00:02:00'))
        self.collect()
        with self.view.content_db() as db:
            db.execute('UPDATE native_runs SET expires=0')
        with self.view.content_db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM native_attribution').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
