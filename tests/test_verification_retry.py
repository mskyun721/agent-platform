import sys
import unittest

from test_evidence import EvidenceTest
from agent_platform_mcp.tools import feature, store


class VerificationRetryTest(EvidenceTest):
    def test_actual_failure_retries_are_bounded_and_waiting(self):
        self.settings["retry"] = {"verification": {"max_attempts": 2, "max_minutes": 1}}
        self.source.write_text("value = 2\n")
        result = self.gate(True)
        self.assertEqual(len(result["retry"]["attempts"]), 2)
        self.assertTrue(result["retry"]["exhausted"])
        self.assertEqual(result["run_state"], "waiting")
        with store.open() as db:
            self.assertEqual(db.connection.execute("SELECT count(*) FROM evidence").fetchone()[0], 2)
            self.assertEqual(db.connection.execute("SELECT state FROM run_control WHERE run_id=?", (result["verification_run_id"],)).fetchone()[0], "waiting")

    def test_default_is_one_and_success_does_not_repeat(self):
        result = self.gate(True)
        self.assertEqual(len(result["retry"]["attempts"]), 1)
        self.assertFalse(result["retry"]["exhausted"])
        self.assertEqual(result["evidence_status"], "complete")

    def test_real_timeout_obeys_total_budget(self):
        self.settings["retry"] = {"verification": {"max_attempts": 5, "max_minutes": 0.002}}
        self.settings["verify_profiles"]["fixture"]["argv"] = [sys.executable, "-c", "import time; time.sleep(60)"]
        result = self.gate(True)
        self.assertEqual(len(result["retry"]["attempts"]), 1)
        self.assertTrue(result["retry"]["exhausted"])

    def test_invalid_budget_cannot_execute(self):
        from agent_platform_mcp.tools import verification
        from unittest.mock import patch
        self.settings["retry"] = {"verification": {"max_attempts": 100}}
        with patch.object(verification, "_attempt", side_effect=AssertionError("must not execute")):
            with self.assertRaises(ValueError):
                self.gate(True)
