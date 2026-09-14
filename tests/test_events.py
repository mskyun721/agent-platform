import sys
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-server/src"))
from agent_platform_mcp.events import RunEvent, ReviewResult, Usage, validate, validate_review, validate_usage


class EventContractTest(unittest.TestCase):
    def setUp(self):
        self.event = RunEvent(
            event_id=str(uuid4()), run_id=str(uuid4()), parent_run_id=None,
            project_id=None, task_id="refactor/platform-events", role="backend",
            event_type="run_started", ts="2026-09-14T00:00:00Z", backend="codex",
            model=None, skill_versions={"qa": "a" * 64}, payload={},
            collection_source="direct", completeness="partial",
        )

    def test_valid_event_and_future_backend(self):
        self.assertEqual(validate(self.event), [])
        self.assertEqual(validate(replace(self.event, backend="future-provider")), [])

    def test_invalid_envelope_fields(self):
        cases = dict(event_id="invalid", run_id="feature:1", parent_run_id=self.event.run_id,
                     schema_version=True, task_id="../escape", role="unknown", event_type="unknown",
                     collection_source="unknown", completeness="complete", project_id="",
                     model=42, skill_versions={"qa": "unhashed"}, payload=[])
        for field, value in cases.items():
            with self.subTest(field=field):
                self.assertTrue(validate(replace(self.event, **{field: value})))

    def test_timestamp_requires_utc(self):
        for timestamp in ("2026-09-14", "2026-09-14T09:00:00+09:00", "invalid", None):
            with self.subTest(timestamp=timestamp):
                self.assertTrue(validate(replace(self.event, ts=timestamp)))
        self.assertEqual(validate(replace(self.event, ts="2026-09-14T00:00:00+00:00")), [])

    def test_json_payload_rejects_nonfinite_unsupported_and_cycles(self):
        cyclic = {}
        cyclic["self"] = cyclic
        for payload in ({"value": float("nan")}, {"value": object()}, cyclic):
            self.assertTrue(validate(replace(self.event, payload=payload)))

    def test_usage_unknown_is_not_zero(self):
        unknown = Usage(None, None, None, None, "native", "unavailable")
        self.assertEqual(validate_usage(unknown), [])
        self.assertTrue(validate_usage(replace(unknown, input_tokens=0)))
        full = replace(unknown, input_tokens=0, output_tokens=0, completeness="full")
        self.assertEqual(validate_usage(full), [])
        self.assertTrue(validate_usage(replace(full, output_tokens=None)))
        for count in (-1, True, 1.5, "0"):
            with self.subTest(count=count):
                self.assertTrue(validate_usage(replace(full, cache_read_tokens=count)))
        self.assertEqual(validate(replace(self.event, event_type="usage", payload=asdict(full))), [])
        self.assertTrue(validate(replace(self.event, event_type="usage", payload={})))

    def test_review_identity_and_enclosing_run(self):
        review = ReviewResult(str(uuid4()), str(uuid4()), str(uuid4()), "human-reviewer",
                              "reviewer", 1, "rejected", "b" * 64, self.event.run_id,
                              "docs/refactor/platform-events/REVIEW.md")
        self.assertEqual(validate_review(review), [])
        event = replace(self.event, role="reviewer", event_type="review_result", payload=asdict(review))
        self.assertEqual(validate(event), [])
        self.assertTrue(validate(replace(event, role="qa")))
        self.assertTrue(validate(replace(event, run_id=str(uuid4()))))
        self.assertTrue(validate(replace(event, payload={})))
        for field, value in dict(decision_id="bad", review_cycle_id="bad", review_attempt_id="bad",
                                 reviewer_id="", role="backend", attempt=True, decision="draft",
                                 code_fingerprint="bad", run_id="feature:1").items():
            with self.subTest(field=field):
                self.assertTrue(validate_review(replace(review, **{field: value})))
        for artifact in ("/docs/REVIEW.md", "docs/../REVIEW.md", "docs\\REVIEW.md", "docs/a\x00.md"):
            with self.subTest(artifact=artifact):
                self.assertTrue(validate_review(replace(review, artifact=artifact)))
