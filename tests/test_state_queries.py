import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from test_store import started
from agent_platform_mcp import events
from agent_platform_mcp.tools import pricing, state_queries, store


class StateQueryTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        mock = patch.dict(os.environ, {"AGENT_PLATFORM_STATE_DB": str(self.root / "state.db")})
        mock.start()
        self.addCleanup(mock.stop)
        self.price = {"price_id": "fixture-v1", "currency": "USD", "as_of": "2026-09-14",
                      "models": {"fixture": {"input_per_mtok": "2", "output_per_mtok": "4",
                                             "cache_read_per_mtok": "0.5", "cache_write_per_mtok": "1",
                                             "input_includes_cache": True}}}

    def add_run(self, usage=None, end=False):
        event = replace(started(), model="fixture", payload={"price_snapshot": pricing.snapshot(self.price, "fixture")})
        with store.open() as db:
            db.record_event(event)
            if usage:
                db.record_usage(event.run_id, usage)
            if end:
                db.record_event(replace(event, event_id=str(uuid4()), event_type="run_ended", payload={"outcome": "completed"}))
        return event

    def test_cache_semantics_snapshot_and_recalculation_are_distinct(self):
        self.add_run(events.Usage(100, 10, 80, 0, "fixture", "full"))
        result = state_queries.usage_summary()
        self.assertEqual(result["tokens"]["input_tokens"], 100)
        self.assertEqual(result["cost"]["estimated"], "0.00012")
        self.price["models"]["fixture"]["input_per_mtok"] = "4"
        self.price["price_id"] = "fixture-v2"
        self.assertEqual(state_queries.usage_summary()["cost"]["estimated"], "0.00012")
        recalculated = state_queries.usage_summary(scenario=self.price)
        self.assertEqual(recalculated["cost"]["estimated"], "0.00016")
        self.assertEqual(recalculated["cost"]["scenario"], "recalculated")

    def test_missing_usage_is_not_zero_or_complete_cost(self):
        self.add_run(events.Usage(0, 0, 0, 0, "fixture", "full"))
        self.add_run()
        result = state_queries.usage_summary()
        self.assertEqual(result["tokens"]["input_tokens"], 0)
        self.assertEqual(result["missing_runs"], 1)
        self.assertEqual(result["missing_fields"]["input_tokens"], 1)
        self.assertIsNone(result["cost"]["estimated"])
        self.assertIsNone(result["cost"]["reported"])

    def test_export_import_idempotence_and_file_overwrite_protection(self):
        self.add_run(events.Usage(100, 10, 80, 0, "fixture", "full"), end=True)
        export = self.root / "export.json"
        state_queries.export_file(str(export))
        with self.assertRaises(FileExistsError):
            state_queries.export_file(str(export))
        with patch.dict(os.environ, {"AGENT_PLATFORM_STATE_DB": str(self.root / "restored.db")}):
            result = state_queries.import_file(str(export))
            self.assertEqual(result["imported_events"], 2)
            self.assertEqual(state_queries.import_file(str(export))["imported_events"], 0)
            self.assertEqual(state_queries.usage_summary()["cost"]["estimated"], "0.00012")

    def test_prune_preserves_active_and_review_referenced_runs(self):
        self.add_run(end=True)
        active = self.add_run()
        pinned = self.add_run(end=True)
        with store.open() as db:
            db.record_review(events.ReviewResult(str(uuid4()), str(uuid4()), str(uuid4()), "human", "reviewer", 1,
                "rejected", "a" * 64, pinned.run_id, "docs/features/sample-task/REVIEW.md"), "project-one", "sample-task")
        result = state_queries.prune("2026-09-15T00:00:00Z")
        self.assertEqual(result["removed_runs"], 1)
        with store.open() as db:
            self.assertEqual({row["run_id"] for row in db.runs()}, {active.run_id, pinned.run_id})
            self.assertEqual(db.review_status("project-one", "sample-task")["reviewer"]["consecutive_rejections"], 1)

    def test_invalid_rates_missing_semantics_and_unknown_snapshot_fields(self):
        for invalid in ("-1", "NaN", "Infinity", True):
            self.price["models"]["fixture"]["input_per_mtok"] = invalid
            with self.assertRaises(ValueError):
                pricing.snapshot(self.price, "fixture")
        self.price["models"]["fixture"]["input_per_mtok"] = "2"
        valid = pricing.snapshot(self.price, "fixture")
        with store.open() as db, self.assertRaises(ValueError):
            db.record_event(replace(started(), model="fixture", payload={"price_snapshot": {**valid, "stdout": "raw"}}))
        del self.price["models"]["fixture"]["input_includes_cache"]
        with self.assertRaises(ValueError):
            pricing.snapshot(self.price, "fixture")
