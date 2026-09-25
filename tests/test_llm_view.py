import json
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
from pathlib import Path
import subprocess

from test_observation import ObservationFixture
from agent_platform_mcp.tools import observation, projects, runner, store


class LLMViewTest(ObservationFixture, unittest.TestCase):
    def view(self):
        from agent_platform_mcp.tools import llm_view
        return llm_view

    def run_cli(self, output='answer'):
        context = projects.resolve('test-project')
        with patch('shutil.which', return_value='/fake/codex'), patch(
            'agent_platform_mcp.tools.monitored_process.run',
            return_value=subprocess.CompletedProcess([], 0, output, '')):
            return observation.observed(context, 'sample-task', 'backend', 'codex', False,
                lambda: {'exit_code': runner.run_cli('codex', ['codex', 'exec', 'private input'], self.root, 5).returncode})

    def test_opt_in_capture_and_default_off(self):
        view = self.view()
        first = self.run_cli()
        self.assertEqual(view.detail(first['run_id'])['content']['status'], 'not_captured')
        view.configure('test-project', True)
        second = self.run_cli('password=private-value\n<script>alert(1)</script>')
        detail = view.detail(second['run_id'])
        self.assertEqual(detail['content']['prompt'], 'private input')
        self.assertNotIn('private-value', detail['content']['response'])
        self.assertGreaterEqual(detail['duration_sec'], 0)
        self.assertIsNone(detail['usage']['input_tokens'])
        with store.open() as db:
            self.assertNotIn('private input', str(db.connection.execute('SELECT event_json FROM events').fetchall()))
        view.configure('test-project', False)
        self.assertEqual(view.detail(self.run_cli()['run_id'])['content']['status'], 'not_captured')

    def test_tokens_native_projection_and_delete(self):
        from uuid import uuid4
        view = self.view()
        view.configure('test-project', True)
        output = '\n'.join(json.dumps(v) for v in [
            {'type': 'thread.started', 'thread_id': str(uuid4())},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'final reply'}},
            {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'output_tokens': 20, 'cached_input_tokens': 30}}])
        run = self.run_cli(output)['run_id']
        self.assertEqual(view.detail(run)['content']['response'], 'final reply')
        self.assertEqual(view.detail(run)['usage']['cache_read_tokens'], 30)
        self.assertEqual(view.list_runs()['runs'][0]['run_id'], run)
        view.purge()
        self.assertEqual(view.detail(run)['content']['status'], 'not_captured')

    def test_http_requires_token_and_rejects_foreign_origin(self):
        view = self.view()
        httpd = view.make_server(0)
        self.addCleanup(httpd.server_close)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        base = f'http://127.0.0.1:{httpd.server_port}'
        with urllib.request.urlopen(base) as response:
            self.assertIn(b'LLM Observability', response.read())
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        for headers in ({}, {'Authorization': 'Bearer ' + httpd.access_token, 'Origin': 'https://evil.example'}):
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(base + '/api/runs', headers=headers))
            self.assertEqual(error.exception.code, 403)
        req = urllib.request.Request(base + '/api/runs', headers={'Authorization': 'Bearer ' + httpd.access_token})
        with urllib.request.urlopen(req) as response:
            self.assertEqual(json.load(response)['runs'], [])

    def test_failure_preserves_prompt_and_reports_no_response(self):
        view = self.view()
        view.configure('test-project', True)
        context = projects.resolve('test-project')
        with patch('shutil.which', return_value='/fake/codex'), patch(
            'agent_platform_mcp.tools.monitored_process.run', side_effect=subprocess.TimeoutExpired('codex', 1)):
            with self.assertRaises(RuntimeError):
                observation.observed(context, 'sample-task', 'backend', 'codex', False,
                    lambda: runner.run_cli('codex', ['codex', 'exec', 'failure input'], self.root, 1))
        run = view.list_runs()['runs'][0]
        self.assertEqual(run['outcome'], 'interrupted')
        content = view.detail(run['run_id'])['content']
        self.assertEqual(content['prompt'], 'failure input')
        self.assertIsNone(content['response'])

    def test_expiry_limits_and_symlink_storage(self):
        view = self.view()
        view.configure('test-project', True)
        run = observation.run_start('sample-task', 'backend', root='test-project')['run_id']
        view.record(run, prompt='x' * (view.MAX_TEXT + 20))
        self.assertTrue(view.detail(run)['content']['prompt_truncated'])
        self.assertEqual(len(view.detail(run)['content']['prompt']), view.MAX_TEXT)
        with patch.object(view.time, 'time', return_value=10**12):
            self.assertEqual(view.detail(run)['content']['status'], 'not_captured')
        path = self.root / 'llm-content.db'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        path.unlink()
        other = self.root / 'untouched'
        other.write_text('keep')
        path.symlink_to(other)
        with self.assertRaises(ValueError):
            view.configure('test-project', True)
        self.assertEqual(other.read_text(), 'keep')

    def test_content_failure_does_not_break_execution(self):
        view = self.view()
        with patch.object(view, 'record', side_effect=OSError('private diagnostic')):
            result = self.run_cli()
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['observability']['content_error'], 'OSError')

    def test_direct_record_via_cli(self):
        import io
        from agent_platform_mcp import cli
        view = self.view()
        view.configure('test-project', True)
        run = observation.run_start('sample-task', 'backend', root='test-project')['run_id']
        with patch('sys.stdin', io.StringIO(json.dumps({'prompt': 'direct input', 'response': 'direct result'}))), patch('sys.stdout', io.StringIO()):
            self.assertEqual(cli.main(['observe', 'record', '--run-id', run]), 0)
        self.assertEqual(view.detail(run)['content']['response'], 'direct result')
