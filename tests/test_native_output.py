import json
import subprocess
import unittest
from unittest.mock import patch
from uuid import uuid4

from test_observation import ObservationFixture
from agent_platform_mcp.tools import native_output, review, runner, state_queries


def output(**usage):
    return "\n".join(json.dumps(row) for row in [
        {"type": "thread.started", "thread_id": str(uuid4())},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "final report"}},
        {"type": "turn.completed", "usage": usage},
    ])


class NativeOutputTest(unittest.TestCase):
    def test_actual_field_shape_and_missing_cache_are_preserved(self):
        body, usage = native_output.codex(output(input_tokens=15557, cached_input_tokens=12160,
                                                cache_write_input_tokens=0, output_tokens=5, reasoning_output_tokens=0))
        self.assertEqual(body, "final report")
        self.assertEqual((usage.input_tokens, usage.cache_read_tokens, usage.output_tokens), (15557, 12160, 5))
        self.assertEqual(usage.completeness, "full")
        _, partial = native_output.codex(output(input_tokens=1, output_tokens=1))
        self.assertIsNone(partial.cache_write_tokens)
        self.assertEqual(partial.completeness, "partial")

    def test_ambiguous_malformed_and_invalid_counts_are_unavailable(self):
        good = output(input_tokens=10, output_tokens=1)
        for value in (good + "\nnot-json", good + "\n" + good, output(input_tokens=-1), output(input_tokens=True)):
            self.assertEqual(native_output.codex(value)[1].completeness, "unavailable")
        self.assertEqual(native_output.codex("legacy report")[0], "legacy report")


class NativeCollectorTest(ObservationFixture, unittest.TestCase):
    def test_real_runner_parses_json_and_persists_only_usage(self):
        raw = output(input_tokens=100, output_tokens=10, cached_input_tokens=80, cache_write_input_tokens=0)
        with patch.object(runner.shutil, "which", return_value="codex"), \
             patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, raw, "")):
            # Avoid patched Git discovery by using the already resolved explicit context.
            context = runner.ProjectContext("test-project", self.root)
            with patch.object(runner, "resolve_project", return_value=context):
                result = review.run("sample-task", cli="codex", root="test-project")
        self.assertEqual(result["observability"]["usage"], "full")
        self.assertEqual(state_queries.usage_summary()["tokens"]["input_tokens"], 100)
