import json
import unittest
from unittest.mock import patch
from test_observation import ObservationFixture


class NativeSessionsTest(ObservationFixture, unittest.TestCase):
    def module(self):
        from agent_platform_mcp.tools import native_sessions
        return native_sessions

    def codex(self):
        return [
            {'type': 'session_meta', 'payload': {'id': 'session', 'cwd': str(self.root)}},
            {'timestamp': '2026-09-25T00:00:00Z', 'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'turn'}},
            {'type': 'turn_context', 'payload': {'model': 'test-model', 'turn_id': 'turn'}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'implement it'}]}},
            {'type': 'token_usage_record', 'payload': {'turn_id': 'turn', 'turn_token_usage': {'input_tokens': 30, 'output_tokens': 8, 'cached_input_tokens': 10}}},
            {'type': 'token_usage_record', 'payload': {'turn_id': 'turn', 'turn_token_usage': {'input_tokens': 40, 'output_tokens': 9, 'cached_input_tokens': 12}}},
            {'timestamp': '2026-09-25T00:00:02Z', 'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'turn', 'last_agent_message': 'done', 'duration_ms': 2000}},
        ]

    def test_codex_turn_snapshot_not_double_counted(self):
        rows = self.module().parse_codex(self.codex(), str(self.root))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['content']['prompt'], 'implement it')
        self.assertEqual(row['content']['response'], 'done')
        self.assertEqual(row['duration_sec'], 2)
        self.assertEqual(row['usage']['input_tokens'], 40)
        self.assertIsNone(row['usage']['cache_write_tokens'])
        self.assertEqual(self.module().parse_codex(self.codex(), '/different'), [])

    def test_claude_message_dedup_and_tool_result_exclusion(self):
        rows = [
            {'type': 'user', 'uuid': 'u', 'sessionId': 's', 'cwd': str(self.root), 'timestamp': '2026-09-25T00:00:00Z', 'message': {'content': 'fix it'}},
            {'type': 'assistant', 'timestamp': '2026-09-25T00:00:01Z', 'message': {'id': 'm', 'model': 'claude-test', 'content': [{'type':'thinking','thinking':'hidden-reasoning-marker'}], 'usage': {'input_tokens': 10, 'output_tokens': 1}}},
            {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': 'DO NOT IMPORT'}]}},
            {'type': 'assistant', 'timestamp': '2026-09-25T00:00:02Z', 'message': {'id': 'm', 'model': 'claude-test', 'content': [{'type':'text','text':'fixed'}], 'stop_reason': 'end_turn', 'usage': {'input_tokens': 10, 'output_tokens': 5}}},
            {'type': 'system', 'subtype': 'turn_duration', 'isMeta': True, 'durationMs': 2300},
        ]
        self.assertEqual(self.module().parse_claude(rows, '/different'), [])
        unscoped = [{k: v for k, v in r.items() if k != 'cwd'} for r in rows]
        self.assertEqual(self.module().parse_claude(unscoped, str(self.root)), [])
        result = self.module().parse_claude(rows, str(self.root))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['usage']['input_tokens'], 10)
        self.assertEqual(result[0]['usage']['output_tokens'], 5)
        self.assertEqual(result[0]['content']['response'], 'fixed')
        self.assertEqual(result[0]['duration_sec'], 2.3)
        self.assertNotIn('DO NOT IMPORT', json.dumps(result))
        self.assertNotIn('hidden-reasoning-marker', json.dumps(result))

    def test_collection_scoped_cached_and_visible(self):
        from agent_platform_mcp.tools import llm_view
        native = self.module()
        sessions = self.root / 'sessions'
        sessions.mkdir()
        source = sessions / 'rollout.jsonl'
        source.write_text('\n'.join(map(json.dumps, self.codex())) + '\n')
        with patch.object(native, 'sources', return_value={'codex': sessions, 'claude': self.root / 'missing'}), patch.object(native.config, 'ROOT', self.root):
            llm_view.configure('test-project', True)
            first = native.collect()
            self.assertEqual(first['codex']['imported'], 1)
            self.assertEqual(native.collect()['codex']['imported'], 0)
            rows = llm_view.list_runs()['runs']
            self.assertEqual(len(rows), 1)
            self.assertEqual(llm_view.detail(rows[0]['run_id'])['content']['response'], 'done')
            llm_view.purge()
            source.write_text(source.read_text() + '{}\n')
            native.collect()
            self.assertEqual(llm_view.list_runs()['runs'], [])

    def test_claude_mixed_workspace_preserves_only_platform_turns(self):
        rows = [
            {'type': 'user', 'uuid': 'a', 'sessionId': 's', 'cwd': str(self.root), 'message': {'content': 'platform first'}},
            {'type': 'assistant', 'message': {'content': 'platform answer'}},
            {'type': 'attachment', 'cwd': '/other'},
            {'type': 'assistant', 'message': {'content': 'foreign response'}},
            {'type': 'user', 'uuid': 'b', 'sessionId': 's', 'message': {'content': 'foreign prompt'}},
            {'type': 'assistant', 'message': {'content': 'foreign answer'}},
            {'type': 'attachment', 'cwd': str(self.root)},
            {'type': 'assistant', 'message': {'content': 'orphan response'}},
            {'type': 'user', 'uuid': 'c', 'sessionId': 's', 'message': {'content': 'platform latest'}},
            {'type': 'assistant', 'message': {'content': 'latest answer'}},
        ]
        result = self.module().parse_claude(rows, str(self.root))
        self.assertEqual([r['content']['prompt'] for r in result], ['platform first', 'platform latest'])
        self.assertEqual([r['content']['response'] for r in result], ['platform answer', 'latest answer'])
        self.assertNotIn('foreign', json.dumps(result))
        self.assertNotIn('orphan', json.dumps(result))
