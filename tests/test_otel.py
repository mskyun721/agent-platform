"""OTel collector control (fake docker on PATH, no real container) and the log-event summary."""
import io
import json
import os
import shutil
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]

FAKE_DOCKER = """#!/bin/sh
printf '%s\\n' "$@" > "$FAKE_DOCKER_LOG"
case "$FAKE_DOCKER_MODE" in
  daemon) echo "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?" >&2; exit 1 ;;
  fail) echo "boom password=supersecretvalue123456" >&2; exit 3 ;;
esac
if [ "$3" = "ps" ] || [ "$4" = "ps" ]; then
  echo '{"Service":"otel-collector","State":"running","Status":"Up 2 minutes","Labels":"private"}'
fi
exit 0
"""


def attr(key, value):
    kind = 'intValue' if type(value) is int else 'doubleValue' if isinstance(value, float) else 'stringValue'
    return {'key': key, 'value': {kind: str(value) if kind == 'intValue' else value}}


def log_line(records):
    return json.dumps({'resourceLogs': [{'resource': {'attributes': []}, 'scopeLogs': [{'logRecords': records}]}]})


def claude_request(session, tokens, cost, ts=1795000000000000000):
    return {'timeUnixNano': str(ts), 'attributes': [
        attr('event.name', 'api_request'), attr('session.id', session), attr('model', 'claude-x'),
        attr('input_tokens', tokens), attr('output_tokens', 2), attr('cache_read_tokens', 3),
        attr('cache_creation_tokens', 4), attr('cost_usd', cost), attr('user.email', 'PRIVATE-EMAIL')]}


class OtelFixture:
    def setUp(self):
        from agent_platform_mcp import config
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        otel = self.root / 'scripts/otel'
        (otel / 'otel-data').mkdir(parents=True)
        shutil.copy(REPO / 'scripts/otel/docker-compose.yml', otel / 'docker-compose.yml')
        self.data = otel / 'otel-data'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'docker-argv.txt'
        for mock in (patch.object(config, 'ROOT', self.root),
                     patch.dict(os.environ, {'PATH': str(self.bin), 'FAKE_DOCKER_LOG': str(self.log), 'FAKE_DOCKER_MODE': 'ok'})):
            mock.start()
            self.addCleanup(mock.stop)

    def install_docker(self):
        docker = self.bin / 'docker'
        docker.write_text(FAKE_DOCKER)
        docker.chmod(docker.stat().st_mode | stat.S_IXUSR)

    def argv(self):
        return self.log.read_text().splitlines()


class CollectorTest(OtelFixture, unittest.TestCase):
    def test_actions_run_only_the_fixed_compose_commands(self):
        from agent_platform_mcp.tools import otel
        self.install_docker()
        compose = str(self.root / 'scripts/otel/docker-compose.yml')
        self.assertEqual(otel.collector('start')['status'], 'started')
        self.assertEqual(self.argv(), ['compose', '-f', compose, 'up', '-d'])
        self.assertEqual(otel.collector('stop')['status'], 'stopped')
        self.assertEqual(self.argv(), ['compose', '-f', compose, 'down'])
        status = otel.collector('status')
        self.assertEqual(self.argv(), ['compose', '-f', compose, 'ps', '--format', 'json'])
        self.assertEqual(status, {'status': 'running', 'services': [
            {'service': 'otel-collector', 'state': 'running', 'status': 'Up 2 minutes'}]})
        with self.assertRaises(ValueError):
            otel.collector('up -d --build')

    def test_missing_docker_and_stopped_daemon_are_unavailable(self):
        from agent_platform_mcp.tools import otel
        self.assertEqual(otel.collector('status'), {'status': 'unavailable', 'reason': 'docker not found'})
        self.install_docker()
        os.environ['FAKE_DOCKER_MODE'] = 'daemon'
        self.assertEqual(otel.collector('start'), {'status': 'unavailable', 'reason': 'daemon not running'})

    def test_other_failure_is_masked_error(self):
        from agent_platform_mcp.tools import otel
        self.install_docker()
        os.environ['FAKE_DOCKER_MODE'] = 'fail'
        result = otel.collector('start')
        self.assertEqual((result['status'], result['exit_code']), ('error', 3))
        self.assertNotIn('supersecretvalue123456', json.dumps(result))

    def test_mcp_and_cli_entry_points(self):
        from agent_platform_mcp import cli, server
        self.install_docker()
        self.assertEqual(server.otel_collector('stop')['status'], 'stopped')
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cli.main(['otel', 'status']), 0)
        self.assertEqual(json.loads(out.getvalue())['status'], 'running')


class SummaryTest(OtelFixture, unittest.TestCase):
    def write(self):
        codex = {'observedTimeUnixNano': '1795000000000000000', 'attributes': [
            attr('event.name', 'codex.sse_event'), attr('event.kind', 'response.completed'),
            attr('conversation.id', 'c1'), attr('model', 'gpt-x'), attr('input_token_count', 50),
            attr('output_token_count', 5), attr('cached_token_count', 7), attr('cache_write_token_count', 0)]}
        prompt = {'attributes': [attr('event.name', 'user_prompt'), attr('prompt', 'PROMPT-BODY-MARKER'), attr('session.id', 's1')]}
        old = claude_request('s-old', 999, 9.0, ts=1700000000000000000)
        (self.data / 'logs.jsonl').write_text('\n'.join([
            log_line([claude_request('s1', 10, 0.5), prompt]),
            log_line([claude_request('s1', 20, 0.25), codex, old]),
            '{"resourceLogs": [truncated-tail',
        ]) + '\n')
        (self.data / 'traces.jsonl').write_text('{"resourceSpans": [{"api_request": "TRACE-MARKER"}]}\n')

    def test_summary_aggregates_log_events_without_content(self):
        from agent_platform_mcp.tools import otel
        self.write()
        result = otel.summary()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['files']['traces.jsonl'][:7], 'skipped')
        sessions = {(r['backend'], r['session_id']): r for r in result['sessions']}
        claude = sessions[('claude', 's1')]
        self.assertEqual((claude['requests'], claude['input_tokens'], claude['cache_write_tokens'], claude['cost_usd']),
                         (2, 30, 8, 0.75))
        codex = sessions[('codex', 'c1')]
        self.assertEqual((codex['input_tokens'], codex['cache_read_tokens'], codex['cost_usd']), (50, 7, None))
        text = json.dumps(result)
        for marker in ('PROMPT-BODY-MARKER', 'PRIVATE-EMAIL', 'TRACE-MARKER'):
            self.assertNotIn(marker, text)
        models = {(m['backend'], m['model']): m for m in result['by_model']}
        self.assertEqual(models[('claude', 'claude-x')]['sessions'], 2)

    def test_since_filters_and_validates(self):
        from agent_platform_mcp import server
        from agent_platform_mcp.tools import otel
        self.write()
        result = otel.summary('2026-01-01')
        self.assertNotIn('s-old', {r['session_id'] for r in result['sessions']})
        self.assertEqual(server.otel_summary('2026-01-01')['sessions_total'], 2)
        with self.assertRaises(ValueError):
            otel.summary('yesterday')

    def test_no_data(self):
        from agent_platform_mcp.tools import otel
        self.assertEqual(otel.summary()['status'], 'no_data')


class UserSettingsTest(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('otel_user_settings', REPO / 'scripts/otel/user_settings.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.lines = []

    def run_main(self, answers):
        replies = iter(answers)

        def ask(_question):
            try:
                return next(replies)
            except StopIteration:
                raise EOFError
        return self.module.main(ask, self.lines.append, {'HOME': str(self.home)})

    def test_declined_changes_nothing_and_shows_diff(self):
        settings = self.home / '.claude/settings.json'
        settings.parent.mkdir()
        settings.write_text(json.dumps({'model': 'keep', 'env': {'OTHER': '1'}}))
        before = settings.read_text()
        self.assertEqual(self.run_main(['n']), 0)  # Codex question gets EOF -> no
        self.assertEqual(settings.read_text(), before)
        self.assertFalse((self.home / '.codex/config.toml').exists())
        self.assertIn('    + CLAUDE_CODE_ENABLE_TELEMETRY=1', self.lines)

    def test_confirmed_apply_keeps_settings_and_backs_up(self):
        settings = self.home / '.claude/settings.json'
        settings.parent.mkdir()
        settings.write_text(json.dumps({'model': 'keep', 'env': {'OTHER': '1'}}))
        codex = self.home / '.codex/config.toml'
        codex.parent.mkdir()
        codex.write_text('model = "x"')
        self.run_main(['y', 'yes'])
        data = json.loads(settings.read_text())
        self.assertEqual((data['model'], data['env']['OTHER']), ('keep', '1'))
        self.assertEqual(data['env']['OTEL_EXPORTER_OTLP_ENDPOINT'], 'http://127.0.0.1:4318')
        self.assertEqual(data['env']['OTEL_RESOURCE_ATTRIBUTES'], 'service.namespace=agent-platform')
        self.assertTrue(list(settings.parent.glob('settings.json.bak-*')))
        self.assertTrue(codex.read_text().startswith('model = "x"\n'))
        self.assertIn('[otel]', codex.read_text())
        self.lines.clear()
        self.run_main([])  # re-run: nothing left to change, no prompt answered
        self.assertTrue(any('이미 적용' in line for line in self.lines))
        self.assertTrue(any('이미 [otel]' in line for line in self.lines))

    def test_invalid_settings_are_not_rewritten(self):
        settings = self.home / '.claude/settings.json'
        settings.parent.mkdir()
        settings.write_text('{broken')
        self.run_main(['y', 'n'])
        self.assertEqual(settings.read_text(), '{broken')

    def test_setup_flag_only_dispatches_to_the_helper(self):
        text = (REPO / 'scripts/setup.sh').read_text()
        self.assertIn('--otel)   exec python3 "$ROOT/scripts/otel/user_settings.py"', text)
