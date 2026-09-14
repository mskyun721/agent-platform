import sys
import unittest
from unittest.mock import patch

from test_observation import ObservationFixture
from agent_platform_mcp import config
from agent_platform_mcp.tools import evidence, feature, fingerprint, store, state_queries


class EvidenceTest(ObservationFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.item = self.root / "docs/features/sample-task"
        self.source = self.root / "app.py"
        self.source.write_text("value = 1\n")
        self.prd = ("---\nagent: planner\nfeature: sample-task\nstatus: draft\ncreated: 2026-09-14\nupdated: 2026-09-14\n---\n"
                    "# Requirement\n## 12. 수락 기준\n| ID | 조건 | 검증 방법 |\n|---|---|---|\n| AC-1 | value is one | Python assertion |\n")
        (self.item / "PRD.md").write_text(self.prd)
        self.settings = {"verify_profiles": {"fixture": {"argv": [sys.executable, "-c", "import app; assert app.value == 1"],
                                                         "scope": {"acs": ["AC-1"]}}}}
        for mock in (patch.object(config, "agent_config", return_value=self.settings),
                     patch.object(feature, "agent_config", return_value=self.settings)):
            mock.start()
            self.addCleanup(mock.stop)

    def gate(self, verify=False):
        return feature.gate_check("sample-task", root="test-project", evidence=True, verify=verify, verify_profile="fixture")

    def test_actual_verification_records_evidence_and_code_change_is_stale(self):
        result = self.gate(True)
        self.assertEqual(result["verification_status"], "passed", result)
        self.assertEqual(result["evidence_status"], "complete", result)
        with store.open() as db:
            self.assertEqual(db.connection.execute("SELECT count(*) FROM evidence").fetchone()[0], 1)
        (self.item / "note.md").write_text("documentation only")
        self.assertEqual(self.gate()["evidence_status"], "complete")
        self.source.write_text("value = 2\n")
        self.assertEqual(self.gate()["evidence_status"], "stale")

    def test_report_mode_then_enforcement_and_failed_verification(self):
        report = self.gate()
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["evidence"]["acs"][0]["status"], "missing")
        self.settings["gate"] = {"evidence_enforced": True}
        self.assertFalse(self.gate()["passed"])
        self.source.write_text("value = 2\n")
        result = self.gate(True)
        self.assertEqual(result["verification_status"], "failed")
        self.assertFalse(result["passed"])
        self.assertEqual(result["evidence"]["acs"][0]["status"], "failed")

    def test_criteria_and_profile_changes_invalidate_old_evidence(self):
        self.assertEqual(self.gate(True)["evidence_status"], "complete")
        (self.item / "PRD.md").write_text(self.prd.replace("value is one", "value must equal one"))
        self.assertEqual(self.gate()["evidence_status"], "stale")
        (self.item / "PRD.md").write_text(self.prd)
        self.settings["verify_profiles"]["fixture"]["timeout_sec"] = 20
        self.assertEqual(self.gate()["evidence_status"], "stale")

    def test_code_mutation_during_test_never_becomes_current_passed_evidence(self):
        self.settings["verify_profiles"]["fixture"]["argv"] = [sys.executable, "-c",
            "from pathlib import Path; Path('app.py').write_text('value = 2\\n')"]
        result = self.gate(True)
        self.assertEqual(result["verification_status"], "passed")
        self.assertEqual(result["evidence_status"], "stale")

    def test_high_findings_and_approval_fingerprint(self):
        self.gate(True)
        current = fingerprint.code_fingerprint(self.root)["fingerprint"]
        review = self.item / "REVIEW.md"
        review.write_text(self.prd.split("# Requirement")[0].replace("agent: planner", "agent: reviewer").replace("status: draft", "status: approved\napproved_fingerprint: " + current)
                          + "# REVIEW\n### [HIGH] Unresolved defect\n- 상태: open\n")
        self.settings["gate"] = {"evidence_enforced": True}
        self.assertFalse(self.gate()["passed"])
        review.write_text(review.read_text().replace("- 상태: open", f"- 상태: resolved ({current})"))
        self.assertTrue(self.gate()["passed"])
        self.source.write_text("value = 3\n")
        self.assertIn("REVIEW.md", self.gate()["evidence"]["approval_stale"])

    def test_missing_mapping_and_storage_failure_cannot_claim_complete_evidence(self):
        del self.settings["verify_profiles"]["fixture"]["scope"]
        self.assertEqual(self.gate(True)["evidence_status"], "evidence_unavailable")
        self.settings["gate"] = {"evidence_enforced": True}
        with patch.object(store, "open", side_effect=store.StoreError("failure")):
            result = self.gate(True)
        self.assertEqual(result["verification_status"], "passed")
        self.assertFalse(result["passed"])

    def test_work_criteria_and_fenced_examples(self):
        (self.item / "WORK.md").write_text("## 4. 검증\n| AC-1 | condition | actual test | result |\n"
                                          "```\n| AC-2 | fake | ignored | |\n```\n")
        criteria = evidence.acceptance_criteria(self.item)
        self.assertEqual([item["id"] for item in criteria], ["AC-1"])
        self.assertEqual(criteria[0]["source"], "WORK.md")

    def test_evidence_survives_snapshot_round_trip(self):
        self.gate(True)
        snapshot = state_queries.export_snapshot()
        with patch.dict("os.environ", {"AGENT_PLATFORM_STATE_DB": str(self.root / "restored.db")}):
            state_queries.import_snapshot(snapshot)
            state_queries.import_snapshot(snapshot)
            with store.open() as db:
                self.assertEqual(db.connection.execute("SELECT count(*) FROM evidence").fetchone()[0], 1)
