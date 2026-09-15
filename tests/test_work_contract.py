from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server/src"))

from agent_platform_mcp.tools import feature, handoff


class WorkContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        env = patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        (self.root / "ARCHITECTURE.md").write_text("# Structure\n", encoding="utf-8")  # P9: required for backend/reviewer
        self.name = "refactor/small-change"

    def work(self, status="approved", risk="low"):
        feature.scaffold(self.name, root=self.root, contract="work-v1")
        path = self.root / "docs" / self.name / "WORK.md"
        path.write_text(path.read_text().replace("status: draft", f"status: {status}")
                        .replace("risk: undecided", f"risk: {risk}"), encoding="utf-8")
        return path

    def artifact(self, filename, agent, status):
        path = self.root / "docs" / self.name / filename
        path.write_text(f"---\nagent: {agent}\nfeature: {self.name}\nstatus: {status}\n"
                        "created: 2026-09-13\nupdated: 2026-09-13\n---\n", encoding="utf-8")

    def test_scaffold_requires_explicit_risk_and_is_single_file(self):
        result = feature.scaffold(self.name, root=self.root, contract="work-v1")
        self.assertEqual(result["created_files"], [f"docs/{self.name}/WORK.md"])
        gate = feature.gate_check(self.name, root=self.root)
        self.assertEqual(gate["track"], "work")
        self.assertFalse(gate["passed"])

    def test_unknown_contract_has_no_filesystem_side_effect(self):
        with self.assertRaises(ValueError):
            feature.scaffold(self.name, root=self.root, contract="unknown")
        self.assertFalse((self.root / "docs").exists())

    def test_legacy_scaffold_still_creates_two_files(self):
        result = feature.scaffold(self.name, root=self.root)
        self.assertEqual(len(result["created_files"]), 2)
        self.assertEqual(feature.gate_check(self.name, root=self.root)["track"], "full")

    def test_work_backend_gate_needs_no_prd_or_task(self):
        self.work()
        self.assertTrue(feature.gate_check(self.name, agent="backend", root=self.root)["passed"])
        self.assertTrue(handoff.validate("planner", "backend", self.name, root=self.root)["passed"])

    def test_draft_is_accepted_for_plan_review_not_implementation(self):
        self.work(status="draft")
        self.assertTrue(handoff.validate("planner", "reviewer", self.name, root=self.root)["passed"])
        self.assertFalse(handoff.validate("planner", "backend", self.name, root=self.root)["passed"])

    def test_invalid_contract_never_falls_back(self):
        path = self.work()
        for value in ("bad-version", ""):
            with self.subTest(value=value):
                original = path.read_text()
                path.write_text(original.replace("contract: work-v1", f"contract: {value}"))
                gate = feature.gate_check(self.name, root=self.root)
                self.assertEqual(gate["track"], "work")
                self.assertFalse(gate["passed"])
                path.write_text(original)

    def test_missing_heading_and_fenced_heading_fail(self):
        path = self.work()
        path.write_text(path.read_text().replace("## 4. 검증", "```\n## 4. 검증\n```"))
        self.assertFalse(feature.gate_check(self.name, root=self.root)["passed"])

    def test_high_risk_requires_reason_and_security_before_qa(self):
        path = self.work(risk="high")
        self.assertFalse(feature.gate_check(self.name, root=self.root)["passed"])
        path.write_text(path.read_text().replace("risk_reason:", "risk_reason: authorization change"))
        self.artifact("REVIEW.md", "reviewer", "approved")
        gate = feature.gate_check(self.name, agent="qa", root=self.root)
        self.assertIn("SECURITY-AUDIT.md", gate["agent_gate"]["missing"])
        self.artifact("SECURITY-AUDIT.md", "security", "approved")
        self.assertTrue(feature.gate_check(self.name, agent="qa", root=self.root)["passed"])

    def test_completion_still_requires_verification(self):
        self.work()
        with patch.object(feature, "agent_config", return_value={}):
            result = handoff.validate("backend", "reviewer", self.name, root=self.root)
        self.assertFalse(result["passed"])
        self.assertEqual(result["verification_status"], "not_run")

    def test_rework_requires_actual_rejected_review(self):
        self.work()
        self.assertFalse(handoff.validate("reviewer", "backend", self.name, root=self.root)["passed"])
        self.artifact("REVIEW.md", "reviewer", "approved")
        self.assertFalse(handoff.validate("reviewer", "backend", self.name, root=self.root)["passed"])
        self.artifact("REVIEW.md", "reviewer", "rejected")
        self.assertTrue(handoff.validate("reviewer", "backend", self.name, root=self.root)["passed"])

    def test_symlink_work_is_not_read(self):
        directory = self.root / "docs" / self.name
        directory.mkdir(parents=True)
        (directory / "WORK.md").symlink_to(ROOT / "templates/WORK.md")
        with self.assertRaisesRegex(ValueError, "symlink"):
            feature.gate_check(self.name, root=self.root)

    def test_cli_forwards_contract_and_root(self):
        from agent_platform_mcp import cli

        with patch.object(cli.feature, "scaffold", return_value={}) as scaffold, patch.object(cli, "_print_result"):
            self.assertEqual(cli.main(["new-feature", self.name, "--root", str(self.root),
                                       "--contract", "work-v1"]), 0)
        scaffold.assert_called_once_with(self.name, root=str(self.root), contract="work-v1")

    def test_mcp_forwards_contract_and_root(self):
        from agent_platform_mcp import server

        with patch.object(server.feature_tools, "scaffold", return_value={}) as scaffold:
            server.feature_scaffold(self.name, root=str(self.root), contract="work-v1")
        scaffold.assert_called_once_with(self.name, root=str(self.root), contract="work-v1")
