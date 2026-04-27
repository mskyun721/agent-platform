from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server" / "src"))

from agent_platform_mcp import observability  # noqa: E402


class FakeSpan:
    def __init__(self) -> None:
        self.end_calls: list[dict] = []

    def end(self, **kwargs):
        self.end_calls.append(kwargs)
        return self


class FakeTrace:
    def __init__(self) -> None:
        self.span_calls: list[dict] = []
        self.span_instance = FakeSpan()

    def span(self, **kwargs):
        self.span_calls.append(kwargs)
        return self.span_instance


class FakeLangfuse:
    def __init__(self) -> None:
        self.trace_calls: list[dict] = []
        self.trace_instance = FakeTrace()

    def trace(self, **kwargs):
        self.trace_calls.append(kwargs)
        return self.trace_instance


class ObservabilityHelpersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client_backup = observability._client
        self.context_backup = observability._HOOK_CONTEXT_FILE
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        context_dir = self.root / ".claude" / "langfuse"
        context_dir.mkdir(parents=True)
        observability._HOOK_CONTEXT_FILE = context_dir / "active-session.json"

    def tearDown(self) -> None:
        observability._client = self.client_backup
        observability._HOOK_CONTEXT_FILE = self.context_backup
        self.temp_dir.cleanup()

    def test_start_cli_span_reuses_hook_trace_context(self) -> None:
        fake_client = FakeLangfuse()
        observability._client = fake_client
        observability._HOOK_CONTEXT_FILE.write_text(
            json.dumps(
                {
                    "session_id": "session-123",
                    "trace_id": "0123456789abcdef0123456789abcdef",
                }
            ),
            encoding="utf-8",
        )

        span = observability.start_cli_span(
            trace_name="gemini-review",
            span_name="gemini-exec",
            metadata={"feature": "langfuse-observability-hardening"},
            prompt="review this feature",
        )

        self.assertIs(span, fake_client.trace_instance.span_instance)
        self.assertEqual(
            fake_client.trace_calls[0]["id"],
            "0123456789abcdef0123456789abcdef",
        )
        self.assertEqual(
            fake_client.trace_calls[0]["metadata"]["session_id"],
            "session-123",
        )
        self.assertEqual(
            fake_client.trace_instance.span_calls[0]["input"]["prompt_summary"]["chars"],
            len("review this feature"),
        )

    def test_end_cli_span_emits_only_summaries(self) -> None:
        span = FakeSpan()

        observability.end_cli_span(
            span,
            stdout="line1\nline2",
            stderr="boom",
            exit_code=1,
            elapsed_sec=2.5,
        )

        payload = span.end_calls[0]
        self.assertNotIn("line1\nline2", json.dumps(payload))
        self.assertEqual(payload["output"]["stdout_summary"]["lines"], 2)
        self.assertEqual(payload["metadata"]["exit_code"], 1)
        self.assertEqual(payload["level"], "ERROR")


if __name__ == "__main__":
    unittest.main()
