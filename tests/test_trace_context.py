"""P8: platform runs carry the W3C trace context of the CLI session that spawned them."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-server/src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from agent_platform_mcp.tools import observation, store  # noqa: E402
from test_observation import ObservationFixture  # noqa: E402

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


class TraceContextTest(ObservationFixture, unittest.TestCase):
    def _run_started_payload(self, run_id: str) -> dict:
        with store.open() as db:
            return db.run(run_id)["payload"]

    def test_run_start_records_traceparent_ids(self) -> None:
        with patch.dict(os.environ, {"TRACEPARENT": TRACEPARENT}):
            run_id = observation.run_start("sample-task", "backend", "claude", root="test-project")["run_id"]

        payload = self._run_started_payload(run_id)
        self.assertEqual(payload["trace_id"], "4bf92f3577b34da6a3ce929d0e0e4736")
        self.assertEqual(payload["span_id"], "00f067aa0ba902b7")

    def test_missing_or_malformed_traceparent_is_omitted(self) -> None:
        for value in (None, "", "garbage", "00-short-00f067aa0ba902b7-01", "01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"):
            with self.subTest(value=value):
                env = {} if value is None else {"TRACEPARENT": value}
                with patch.dict(os.environ, env, clear=False):
                    if value is None:
                        os.environ.pop("TRACEPARENT", None)
                    run_id = observation.run_start("sample-task", "backend", "claude", root="test-project")["run_id"]
                payload = self._run_started_payload(run_id)
                self.assertNotIn("trace_id", payload)
                self.assertNotIn("span_id", payload)

    def test_parse_traceparent_helper(self) -> None:
        self.assertEqual(observation.parse_traceparent(TRACEPARENT),
                         {"trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "span_id": "00f067aa0ba902b7"})
        self.assertIsNone(observation.parse_traceparent("00-" + "0" * 32 + "-00f067aa0ba902b7-01"), "all-zero trace id is invalid")
        self.assertIsNone(observation.parse_traceparent(None))

    def test_runs_listing_exposes_trace_id(self) -> None:
        with patch.dict(os.environ, {"TRACEPARENT": TRACEPARENT}):
            observation.run_start("sample-task", "reviewer", "claude", root="test-project")
        with store.open() as db:
            runs = db.runs(project_id="test-project")
        self.assertEqual(runs[-1]["payload"]["trace_id"], "4bf92f3577b34da6a3ce929d0e0e4736")


if __name__ == "__main__":
    unittest.main()
