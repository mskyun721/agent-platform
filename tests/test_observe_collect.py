"""observe collect: one-shot import, registered-project scope, subagent transcripts, hooks, MCP."""
import asyncio
import io
import json
import sqlite3
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from test_observation import ObservationFixture

REPO = Path(__file__).resolve().parents[1]


def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(map(json.dumps, rows)) + '\n')


def claude_turn(cwd, uuid, prompt, sidechain=False, session='s1'):
    flags = {'isSidechain': True, 'agentId': 'a1'} if sidechain else {}
    return [
        {'type': 'user', 'uuid': uuid, 'sessionId': session, 'cwd': cwd, 'timestamp': '2026-11-23T00:00:00Z',
         'message': {'content': prompt}, **flags},
        {'type': 'assistant', 'timestamp': '2026-11-23T00:00:01Z', 'cwd': cwd, **flags,
         'message': {'id': 'm-' + uuid, 'model': 'claude-test', 'stop_reason': 'end_turn',
                     'content': [{'type': 'text', 'text': 'answer ' + uuid}],
                     'usage': {'input_tokens': 10, 'output_tokens': 2, 'cache_read_input_tokens': 3,
                               'cache_creation_input_tokens': 4}}},
    ]


def codex_rows(cwd, session, turn, prompt, source='cli', extra_meta=None):
    meta = {'id': session, 'cwd': cwd, 'source': source, **(extra_meta or {})}
    return [
        {'type': 'session_meta', 'payload': meta},
        {'timestamp': '2026-11-23T00:00:00Z', 'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': turn}},
        {'type': 'turn_context', 'payload': {'model': 'codex-test', 'turn_id': turn, 'cwd': cwd}},
        {'type': 'event_msg', 'payload': {'type': 'user_message', 'message': prompt}},
        {'type': 'token_usage_record', 'payload': {'turn_id': turn, 'turn_token_usage': {
            'input_tokens': 20, 'output_tokens': 5, 'cached_input_tokens': 1, 'cache_write_input_tokens': 0}}},
        {'timestamp': '2026-11-23T00:00:03Z', 'type': 'event_msg',
         'payload': {'type': 'task_complete', 'turn_id': turn, 'last_agent_message': 'ok'}},
    ]


class CollectFixture(ObservationFixture):
    """Platform root = conftest copy (config.ROOT); registered project = self.root ('test-project')."""

    def setUp(self):
        super().setUp()
        from agent_platform_mcp import config
        from agent_platform_mcp.tools import llm_view, native_sessions
        self.native, self.view = native_sessions, llm_view
        self.platform = str(config.ROOT.resolve())
        self.home = self.root / 'home'
        self.claude, self.codex = self.home / 'claude', self.home / 'codex'
        self.claude.mkdir(parents=True)
        self.codex.mkdir(parents=True)
        mock = patch.object(native_sessions, 'sources', return_value={'codex': self.codex, 'claude': self.claude})
        mock.start()
        self.addCleanup(mock.stop)

    def stored(self):
        with self.view.content_db() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM native_runs')]


class RegisteredScopeTest(CollectFixture, unittest.TestCase):
    def test_registered_project_session_is_attributed_and_capture_off_is_excluded(self):
        jsonl(self.claude / 'proj' / 's1.jsonl', claude_turn(str(self.root), 'u1', 'project prompt'))
        jsonl(self.claude / 'plat' / 's2.jsonl', claude_turn(self.platform, 'u2', 'platform prompt', session='s2'))
        jsonl(self.codex / 'r1.jsonl', codex_rows(str(self.root), 'c1', 't1', 'codex project prompt'))
        self.view.configure('test-project', True)

        result = self.native.collect_once('test-project')

        self.assertEqual(result['status'], 'collected')
        self.assertFalse(result['truncated'])
        self.assertEqual(result['scope'], [{'workspace': str(self.root), 'project_id': 'test-project'}])
        self.assertEqual((result['claude']['imported'], result['codex']['imported']), (1, 1))
        rows = self.stored()
        self.assertEqual({r['project_id'] for r in rows}, {'test-project'})
        self.assertEqual({r['workspace'] for r in rows}, {str(self.root)})
        self.assertNotIn('platform prompt', json.dumps(rows))  # platform capture is off

    def test_capture_off_root_is_skipped_without_reading_transcripts(self):
        jsonl(self.claude / 'proj' / 's1.jsonl', claude_turn(str(self.root), 'u1', 'prompt'))
        with patch.object(self.native, '_parse', side_effect=AssertionError('must not parse')):
            result = self.native.collect_once('test-project')
        self.assertEqual((result['status'], result['reason']), ('skipped', 'capture disabled'))
        self.assertEqual(self.stored(), [])

    def test_platform_root_collects_enabled_registered_projects_too(self):
        jsonl(self.claude / 'proj' / 's1.jsonl', claude_turn(str(self.root), 'u1', 'project prompt'))
        jsonl(self.claude / 'plat' / 's2.jsonl', claude_turn(self.platform, 'u2', 'platform prompt', session='s2'))
        self.view.configure(self.platform, True)
        self.view.configure('test-project', True)
        result = self.native.collect_once(self.platform)
        self.assertEqual(result['claude']['imported'], 2)
        self.assertEqual({(r['workspace'], r['project_id']) for r in self.stored()},
                         {(self.platform, None), (str(self.root), 'test-project')})

    def test_scope_change_revisits_unchanged_files(self):
        jsonl(self.claude / 'proj' / 's1.jsonl', claude_turn(str(self.root), 'u1', 'project prompt'))
        self.view.configure(self.platform, True)
        self.assertEqual(self.native.collect_once(self.platform)['claude']['imported'], 0)
        self.view.configure('test-project', True)
        self.assertEqual(self.native.collect_once(self.platform)['claude']['imported'], 1)
        self.assertEqual(self.native.collect_once(self.platform)['claude']['unchanged_files'], 1)

    def test_status_reports_last_collect_and_scope(self):
        from agent_platform_mcp.tools import doctor
        self.view.configure('test-project', True)
        jsonl(self.claude / 'proj' / 's1.jsonl', claude_turn(str(self.root), 'u1', 'project prompt'))
        self.assertIsNone(doctor.observation_status('test-project')['last_collect'])
        self.native.collect_once('test-project')
        status = doctor.observation_status('test-project')
        self.assertEqual(status['collection_scope'], 'platform-and-registered-projects')
        self.assertTrue(status['supported_workspace'])
        self.assertEqual(status['last_collect']['imported'], {'claude': 1, 'codex': 0})
        self.assertEqual(status['backends']['claude']['stored_turns'], 1)


class SubagentTest(CollectFixture, unittest.TestCase):
    def test_claude_subagent_transcript_is_collected_with_agent_type(self):
        session = self.claude / 'proj' / 's1'
        jsonl(self.claude / 'proj' / 's1.jsonl',
              claude_turn(str(self.root), 'u1', 'parent prompt')
              + claude_turn(str(self.root), 'x1', 'embedded sidechain must not merge', sidechain=True))
        jsonl(session / 'subagents' / 'agent-a1.jsonl', claude_turn(str(self.root), 'u9', 'subagent task', sidechain=True))
        (session / 'subagents' / 'agent-a1.meta.json').write_text(json.dumps(
            {'agentType': 'backend', 'description': 'META DESCRIPTION MUST NOT BE STORED'}))
        self.view.configure('test-project', True)

        result = self.native.collect_once('test-project')

        self.assertEqual((result['claude']['imported'], result['claude']['subagent_turns']), (2, 1))
        rows = {r['content']['prompt']: r for r in self.stored()}
        self.assertEqual(set(rows), {'parent prompt', 'subagent task'})
        self.assertEqual((rows['subagent task']['role'], rows['subagent task']['agent_type']), ('subagent', 'backend'))
        self.assertEqual(rows['subagent task']['usage']['input_tokens'], 10)
        self.assertEqual(rows['parent prompt']['role'], 'direct')
        self.assertNotIn('META DESCRIPTION', json.dumps(rows))

    def test_codex_forked_subagent_skips_replayed_parent_history(self):
        cwd = str(self.root)
        parent = codex_rows(cwd, 'parent', 'p1', 'parent prompt')
        meta = {'subagent_history_start_ordinal': 1 + len(parent), 'forked_from_id': 'parent'}
        child = codex_rows(cwd, 'child', 'k1', 'child task', source={'subagent': {'thread_spawn': {}}}, extra_meta=meta)
        # Fork layout: own meta, then the parent's meta and turns, then the subagent's own turn.
        jsonl(self.codex / 'child.jsonl', [child[0], *parent, *child[1:]])
        jsonl(self.codex / 'parent.jsonl', parent)
        self.view.configure('test-project', True)

        self.native.collect_once('test-project')

        rows = sorted(self.stored(), key=lambda r: r['session_id'])
        self.assertEqual([(r['session_id'], r['role'], r['content']['prompt']) for r in rows],
                         [('child', 'subagent', 'child task'), ('parent', 'direct', 'parent prompt')])


    def test_codex_fork_real_layout_uses_child_token_totals(self):  # REVIEW M-2, L-1
        cwd = str(self.root)
        sub = {'subagent': {'thread_spawn': {}}}

        def event(kind, **payload):
            return {'timestamp': '2026-11-23T00:00:00Z', 'type': 'event_msg', 'payload': {'type': kind, **payload}}

        def total(value):
            return event('token_count', info={'total_token_usage': {
                'input_tokens': value, 'output_tokens': value // 10, 'cached_input_tokens': 0, 'cache_write_input_tokens': 0}})
        parent_meta = {'type': 'session_meta', 'payload': {'id': 'parent', 'cwd': cwd, 'source': 'cli'}}
        parent_turn = [event('task_started', turn_id='p1'), {'type': 'turn_context', 'payload': {'model': 'm', 'cwd': cwd}},
                       event('user_message', message='parent prompt'), total(1000), event('task_complete', last_agent_message='ok')]
        jsonl(self.codex / 'parent.jsonl', [parent_meta, *parent_turn])
        # Real fork: own meta, parent meta, parent history (no parent token_count is replayed), the parent's
        # unfinished task_started one line before the ordinal, thread_settings_applied @ordinal, own turns after.
        copied = [row for row in parent_turn if row['payload'].get('type') != 'token_count']
        history = [parent_meta, *copied, event('task_started', turn_id='p2')]
        own = [event('thread_settings_applied'),
               event('task_started', turn_id='k1'), event('user_message', message='child one'), total(300),
               event('task_complete', last_agent_message='a'),
               event('task_started', turn_id='k2'), event('user_message', message='child two'), total(450),
               event('task_complete', last_agent_message='b')]
        lines = [json.dumps(r) for r in history]
        lines.insert(2, '{"broken json')  # a damaged line must not shift the raw-line ordinal
        ordinal = 1 + len(lines)
        child_meta = {'type': 'session_meta', 'payload': {'id': 'child', 'cwd': cwd, 'source': sub,
                                                           'subagent_history_start_ordinal': ordinal}}
        path = self.codex / 'child.jsonl'
        path.write_text('\n'.join([json.dumps(child_meta), *lines, *map(json.dumps, own)]) + '\n')
        self.view.configure('test-project', True)

        self.native.collect_once('test-project')

        rows = {r['content']['prompt']: r for r in self.stored()}
        self.assertEqual(set(rows), {'parent prompt', 'child one', 'child two'})
        self.assertEqual(rows['parent prompt']['usage']['input_tokens'], 1000)
        self.assertEqual((rows['child one']['usage']['input_tokens'], rows['child two']['usage']['input_tokens']), (300, 150))
        self.assertEqual({rows[p]['session_id'] for p in ('child one', 'child two')}, {'child'})
        parent_ids = {r['run_id'] for r in self.native.parse_codex(self.native._rows(self.codex / 'parent.jsonl'), cwd)}
        child_ids = {r['run_id'] for r in self.native.parse_codex(self.native._rows(path), cwd)}
        self.assertFalse(parent_ids & child_ids)


class BoundsTest(CollectFixture, unittest.TestCase):
    def test_budget_exhaustion_reports_truncated_and_resumes_next_call(self):
        for index in range(3):
            jsonl(self.claude / 'proj' / f's{index}.jsonl', claude_turn(str(self.root), f'u{index}', f'p{index}', session=f's{index}'))
        self.view.configure('test-project', True)
        first = self.native.collect_once('test-project', budget_sec=0)
        self.assertTrue(first['truncated'])
        self.assertEqual(first['claude']['imported'], 0)
        second = self.native.collect_once('test-project')
        self.assertFalse(second['truncated'])
        self.assertEqual(second['claude']['imported'], 3)

    def test_failure_is_reported_never_raised(self):
        self.view.configure('test-project', True)
        with patch.object(self.native, 'collect', side_effect=RuntimeError('boom')):
            result = self.native.collect_once('test-project')
        self.assertEqual((result['status'], result['error']), ('error', 'RuntimeError'))
        self.assertNotIn('boom', json.dumps(result))

    def test_concurrent_collection_is_skipped(self):
        self.view.configure('test-project', True)
        with self.native._single_run() as acquired:
            self.assertTrue(acquired)
            result = self.native.collect_once('test-project')
        self.assertEqual((result['status'], result['reason']), ('skipped', 'collection already running'))

    def test_skipped_run_is_redone_once_by_the_holder(self):  # REVIEW L-2
        self.view.configure('test-project', True)
        real, nested = self.native.collect, []

        def collect(root, budget):
            if not nested:  # a SessionEnd hook arrives while the Stop collection runs
                nested.append(self.native.collect_once('test-project'))
            return real(root, budget)
        with patch.object(self.native, 'collect', side_effect=collect) as spy:
            result = self.native.collect_once('test-project')
        self.assertEqual((nested[0]['status'], nested[0]['rerun_requested']), ('skipped', True))
        self.assertEqual(spy.call_count, 2)
        self.assertTrue(result['rerun'])
        self.assertEqual(self.native.collect_once('test-project').get('rerun'), None)  # request consumed

    def test_lock_does_not_open_the_state_db(self):  # REVIEW L-2
        with patch.object(self.native.store, 'open', side_effect=AssertionError('state db opened')):
            with self.native._single_run() as run:
                self.assertTrue(run)

    def test_long_run_is_over_budget_not_truncated(self):  # REVIEW L-3
        def slow(root, budget):
            time.sleep(0.05)
            return {'status': 'collected', 'truncated': False}
        with patch.object(self.native, 'collect', side_effect=slow), patch.object(self.native, 'save_health'):
            result = self.native.collect_once('test-project', budget_sec=0.01)
        self.assertEqual((result['truncated'], result['over_budget']), (False, True))

    def test_hook_collects_enabled_projects_while_platform_capture_is_off(self):  # SECURITY I7
        from agent_platform_mcp import cli
        jsonl(self.claude / 'proj' / 's1.jsonl', claude_turn(str(self.root), 'u1', 'project prompt'))
        self.view.configure('test-project', True)
        self.assertEqual(self.native.collect_once(self.platform)['reason'], 'capture disabled')
        out = io.StringIO()
        with redirect_stdout(out):
            cli.main(['observe', 'collect', '--root', self.platform, '--all-enabled'])
        self.assertEqual(json.loads(out.getvalue())['claude']['imported'], 1)
        self.assertEqual({r['project_id'] for r in self.stored()}, {'test-project'})

    def test_cli_collect_exits_zero_on_failure(self):
        from agent_platform_mcp import cli
        out = io.StringIO()
        with patch.object(self.native, 'collect', side_effect=OSError('disk')), redirect_stdout(out):
            code = cli.main(['observe', 'collect', '--root', 'test-project'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())['status'], 'error')

    def test_cli_collect_finishes_within_budget(self):
        from agent_platform_mcp import cli
        for index in range(30):
            jsonl(self.claude / 'proj' / f's{index}.jsonl', claude_turn(str(self.root), f'u{index}', f'p{index}', session=f's{index}'))
        self.view.configure('test-project', True)
        out, started = io.StringIO(), time.monotonic()
        with redirect_stdout(out):
            self.assertEqual(cli.main(['observe', 'collect', '--root', 'test-project']), 0)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(json.loads(out.getvalue())['claude']['imported'], 30)


class ContentLockTest(CollectFixture, unittest.TestCase):  # REVIEW M-1
    def other(self, timeout=0.3):
        with self.view.store.open() as state:
            path = state.path.parent / 'llm-content.db'
        return sqlite3.connect(path, timeout=timeout)

    def short_timeout(self):
        real = sqlite3.connect
        return patch.object(self.view.sqlite3, 'connect', side_effect=lambda path, timeout: real(path, timeout=0.3))

    def test_open_without_expired_rows_takes_no_write_lock(self):
        self.view.configure('test-project', True)
        writer = self.other()
        self.addCleanup(writer.close)
        writer.execute('BEGIN IMMEDIATE')  # another process is writing
        with self.short_timeout(), self.view.content_db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM native_runs').fetchone()[0], 0)
        writer.rollback()

    def test_collect_commits_per_file_so_other_writers_proceed(self):
        for index in range(2):
            jsonl(self.claude / 'proj' / f's{index}.jsonl', claude_turn(str(self.root), f'u{index}', f'p{index}', session=f's{index}'))
        self.view.configure('test-project', True)
        real, seen = self.native._parse, []

        def parse(backend, path, workspaces):
            if seen:  # second file: the first one must already be committed and the DB writable
                other = self.other()
                try:
                    seen.append(other.execute('SELECT COUNT(*) FROM native_runs').fetchone()[0])
                    other.execute("INSERT INTO capture VALUES ('/elsewhere', 0)")
                    other.commit()
                finally:
                    other.close()
            seen.append(path.name)
            return real(backend, path, workspaces)
        with patch.object(self.native, '_parse', side_effect=parse):
            result = self.native.collect_once('test-project')
        self.assertEqual((result['claude']['imported'], result['claude']['errors']), (2, 0))
        self.assertEqual(seen[1], 1)

    def test_serve_poll_skips_a_tick_while_another_process_collects(self):
        class Server:
            collector_status = {'checked_at': 1}
        server = Server()
        with patch.object(self.native, 'collect', side_effect=AssertionError('must not collect')):
            with self.native._single_run() as run:
                self.assertTrue(run)
                self.view.poll(server)
                self.assertFalse(run.take_rerun())  # serve does not queue a rerun: it polls again in 5 s
        self.assertEqual(server.collector_status['skipped'], 'collection already running')
        with patch.object(self.native, 'collect', return_value={'status': 'collected'}) as collect:
            self.view.poll(server)
        collect.assert_called_once_with()


class McpToolsTest(CollectFixture, unittest.TestCase):
    def call(self, name, **arguments):
        from agent_platform_mcp import server
        return asyncio.run(server.mcp.call_tool(name, arguments))

    def test_observe_tools_are_registered(self):
        from agent_platform_mcp import server
        names = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
        self.assertLessEqual({'observe_status', 'observe_efficiency', 'observe_collect', 'observe_capture', 'doctor'}, names)

    def test_capture_states_retention_and_content_storage(self):
        from agent_platform_mcp import server
        preview = server.observe_capture('test-project', 'on')
        self.assertEqual((preview['status'], preview['retention_days'], preview['project_id']),
                         ('confirmation_required', 7, 'test-project'))
        self.assertIn('prompt/response text', preview['stores'])
        self.assertFalse(server.observe_status('test-project')['capture_enabled'])  # unconfirmed: nothing changed
        on = server.observe_capture('test-project', 'on', confirm=True)
        self.assertEqual({k: on[k] for k in ('capture_enabled', 'retention_days', 'stores_content', 'project_id')},
                         {'capture_enabled': True, 'retention_days': 7, 'stores_content': True, 'project_id': 'test-project'})
        off = server.observe_capture('test-project', 'off')
        self.assertEqual((off['capture_enabled'], off['stores_content']), (False, False))
        with self.assertRaises(ValueError):
            server.observe_capture('test-project', 'maybe')

    def test_collect_status_efficiency_doctor_via_server(self):
        from agent_platform_mcp import server
        jsonl(self.claude / 'proj' / 's1.jsonl', claude_turn(str(self.root), 'u1', 'project prompt'))
        self.assertEqual(server.observe_collect('test-project')['status'], 'skipped')
        server.observe_capture('test-project', 'on', confirm=True)
        self.assertEqual(server.observe_collect('test-project')['claude']['imported'], 1)
        self.assertTrue(server.observe_status('test-project')['capture_enabled'])
        self.assertEqual(server.observe_efficiency('test-project')['sample_records'], 1)
        with patch('agent_platform_mcp.tools.doctor.shutil.which', return_value=None):
            report = server.doctor('test-project')
        self.assertEqual(report['observation']['backends']['claude']['stored_turns'], 1)


class HookConfigTest(unittest.TestCase):
    def test_sync_generates_collect_hooks_idempotently_and_keeps_others(self):
        import tempfile
        import sync_claude_settings as sync
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            settings = repo / '.claude/settings.json'
            settings.parent.mkdir()
            other = {'hooks': [{'type': 'command', 'command': 'other'}]}
            stale = {'hooks': [{'type': 'command', 'command': 'python3 old/scripts/hooks/observe_collect.py', 'timeout': 99}]}
            settings.write_text(json.dumps({'hooks': {'Stop': [other, stale]}}))
            self.assertEqual(sync.sync_project_hooks(repo, check=True), ['settings.json'])
            self.assertIn('old/', settings.read_text())  # check never writes
            self.assertEqual(sync.sync_project_hooks(repo), ['settings.json'])
            hooks = json.loads(settings.read_text())['hooks']
            self.assertEqual(hooks['Stop'], [other, sync.COLLECT_HOOK])
            self.assertEqual(hooks['SessionEnd'], [sync.COLLECT_HOOK])
            self.assertEqual(sync.sync_project_hooks(repo), [])

    def test_tracked_settings_and_codex_hooks_run_the_collect_launcher(self):
        import sync_claude_settings as sync
        hooks = json.loads((REPO / '.claude/settings.json').read_text())['hooks']
        for event in ('Stop', 'SessionEnd'):
            self.assertIn(sync.COLLECT_HOOK, hooks[event])
        # .codex/hooks.json is local and generated (a fresh checkout has none): check the generated entry.
        command = sync.codex_collect_hook(REPO)['hooks'][0]['command']
        self.assertRegex(command, r"^python3 '/[^']*/scripts/hooks/observe_collect\.py' ")  # absolute, quoted (SECURITY L1)
        self.assertNotIn('$(', command)
        self.assertTrue(command.endswith('|| true'))  # never a non-zero (blocking) hook exit

    def test_sync_writes_codex_hook_with_quoted_absolute_path(self):  # SECURITY L1
        import tempfile
        import sync_claude_settings as sync
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "it's here"
            (repo / '.codex').mkdir(parents=True)
            hooks = repo / '.codex/hooks.json'
            graphify = {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': 'graphify hook-check'}]}
            old = {'hooks': [{'type': 'command', 'command': 'python3 "$(git rev-parse --show-toplevel)/scripts/hooks/observe_collect.py"'}]}
            hooks.write_text(json.dumps({'hooks': {'PreToolUse': [graphify], 'Stop': [old]}}))
            self.assertEqual(sync.sync_codex_hooks(repo, check=True), ['.codex/hooks.json'])
            self.assertEqual(sync.sync_codex_hooks(repo), ['.codex/hooks.json'])
            data = json.loads(hooks.read_text())['hooks']
            self.assertEqual(data['PreToolUse'], [graphify])
            command = data['Stop'][0]['hooks'][0]['command']
            self.assertEqual(len(data['Stop']), 1)
            import shlex
            self.assertEqual(shlex.split(command)[1], str(repo.resolve() / 'scripts/hooks/observe_collect.py'))
            self.assertEqual(sync.sync_codex_hooks(repo), [])

    def test_codex_hooks_file_is_local_and_not_tracked(self):
        import subprocess
        tracked = subprocess.run(['git', 'ls-files', '.codex/hooks.json'], cwd=REPO, capture_output=True, text=True)
        self.assertEqual(tracked.returncode, 0)
        self.assertEqual(tracked.stdout.strip(), '')  # never commit a machine-specific absolute path
        ignored = subprocess.run(['git', 'check-ignore', '-q', '.codex/hooks.json'], cwd=REPO)
        self.assertEqual(ignored.returncode, 0)

    def test_sync_creates_missing_codex_hooks_with_default_entries(self):
        import tempfile
        import sync_claude_settings as sync
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            hooks = repo / '.codex/hooks.json'
            self.assertEqual(sync.sync_codex_hooks(repo, check=True), ['.codex/hooks.json'])  # missing = drift
            self.assertFalse((repo / '.codex').exists())  # check never writes
            self.assertEqual(sync.sync_codex_hooks(repo), ['.codex/hooks.json'])
            data = json.loads(hooks.read_text())['hooks']
            self.assertEqual(data['PreToolUse'], sync.CODEX_DEFAULT_HOOKS['PreToolUse'])
            self.assertEqual(data['PreToolUse'][0]['hooks'][0]['command'], 'graphify hook-check')
            self.assertEqual(data['Stop'], [sync.codex_collect_hook(repo)])
            self.assertEqual(sync.sync_codex_hooks(repo, check=True), [])
            self.assertEqual(sync.sync_codex_hooks(repo), [])

    def test_sync_keeps_user_codex_entries_and_does_not_readd_defaults(self):
        import tempfile
        import sync_claude_settings as sync
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / '.codex').mkdir()
            hooks = repo / '.codex/hooks.json'
            mine = {'hooks': [{'type': 'command', 'command': 'echo mine'}]}
            hooks.write_text(json.dumps({'hooks': {'Stop': [mine], 'UserPromptSubmit': [mine]}}))
            self.assertEqual(sync.sync_codex_hooks(repo), ['.codex/hooks.json'])
            data = json.loads(hooks.read_text())['hooks']
            self.assertEqual(data['Stop'], [mine, sync.codex_collect_hook(repo)])
            self.assertEqual(data['UserPromptSubmit'], [mine])
            self.assertNotIn('PreToolUse', data)  # defaults only seed a missing file

    def test_sync_rejects_codex_hooks_symlink_or_directory(self):
        import tempfile
        import sync_claude_settings as sync
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / 'repo'
            outside = Path(temp) / 'outside'
            outside.mkdir()
            repo.mkdir()
            (repo / '.codex').symlink_to(outside)
            with self.assertRaises(ValueError):
                sync.sync_codex_hooks(repo)
            self.assertEqual(list(outside.iterdir()), [])
            (repo / '.codex').unlink()
            (repo / '.codex/hooks.json').mkdir(parents=True)
            with self.assertRaises(ValueError):
                sync.sync_codex_hooks(repo)

    def test_agents_only_cli_creates_missing_codex_hooks(self):
        import shutil
        import subprocess
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            shutil.copytree(REPO / '.claude/agents', repo / '.claude/agents')
            shutil.copytree(REPO / 'standards/agents', repo / 'standards/agents')
            shutil.copy(REPO / '.agent-config.json', repo / '.agent-config.json')
            script = REPO / 'scripts/sync_claude_settings.py'
            check = subprocess.run([sys.executable, str(script), '--repo-root', str(repo), '--check'],
                                   capture_output=True, text=True)
            self.assertEqual(check.returncode, 1)
            self.assertIn('.codex/hooks.json', check.stdout)
            done = subprocess.run([sys.executable, str(script), '--repo-root', str(repo), '--agents-only'],
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertTrue((repo / '.codex/hooks.json').is_file())
            again = subprocess.run([sys.executable, str(script), '--repo-root', str(repo), '--check'],
                                   capture_output=True, text=True)
            self.assertEqual((again.returncode, again.stdout.strip()), (0, 'up to date'))

    def test_otel_compose_files_are_edit_denied(self):  # SECURITY L4
        import sync_claude_settings as sync
        rules = sync.deny_rules(REPO)
        for name in ('scripts/otel/docker-compose.yml', 'scripts/otel/otel-collector-config.yaml'):
            for tool in ('Edit', 'Write'):
                self.assertIn(f'{tool}(/{REPO.resolve()}/{name})', rules)

    def test_launcher_detaches_fixed_command_and_returns(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('observe_collect', REPO / 'scripts/hooks/observe_collect.py')
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        with patch.object(launcher.shutil, 'which', return_value='/bin/uv'), patch.object(launcher.subprocess, 'Popen') as popen:
            self.assertEqual(launcher.main(), 0)
        argv, options = popen.call_args.args[0], popen.call_args.kwargs
        self.assertEqual(argv[-5:], ['observe', 'collect', '--root', str(launcher.ROOT), '--all-enabled'])
        self.assertTrue(options['start_new_session'])
        self.assertEqual(options['stdout'], launcher.subprocess.DEVNULL)
        with patch.object(launcher.shutil, 'which', return_value=None), patch.object(launcher.subprocess, 'Popen') as popen:
            self.assertEqual(launcher.main(), 0)
        popen.assert_not_called()
        with patch.object(launcher.shutil, 'which', return_value='/bin/uv'), \
             patch.object(launcher.subprocess, 'Popen', side_effect=OSError):
            self.assertEqual(launcher.main(), 0)
