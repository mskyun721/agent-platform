"""Real local verification across the single-work lifecycle; no AI or remote services."""

import json
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


class WorkLifecycleTest(unittest.TestCase):
    def test_small_fix_from_scaffold_through_failure_rework_and_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory).resolve()
            subprocess.run(["git", "init", "-q", str(project)], check=True, capture_output=True)
            (project / "ARCHITECTURE.md").write_text("# Structure\n", encoding="utf-8")  # P9: required for backend/reviewer
            environment = {**os.environ, "AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(project),
                           "PYTHONPATH": str(ROOT / "mcp-server/src")}
            created = subprocess.run(
                [sys.executable, "-m", "agent_platform_mcp.cli", "new-feature", "fix/addition",
                 "--root", str(project), "--contract", "work-v1"],
                env=environment, capture_output=True, text=True, check=True, timeout=30,
            )
            self.assertEqual(json.loads(created.stdout)["created_files"], ["docs/fix/addition/WORK.md"])
            work = project / "docs/fix/addition/WORK.md"
            work.write_text(work.read_text().replace("risk: undecided", "risk: low")
                            .replace("- 목표와 수락 조건:", "- AC-1: addition returns the arithmetic sum."))
            source = project / "calculator.py"
            source.write_text("def add(a, b):\n    return a - b\n")
            (project / "test_calculator.py").write_text(
                "import unittest\nfrom calculator import add\n"
                "class AdditionTest(unittest.TestCase):\n"
                "    def test_positive(self):\n        self.assertEqual(add(2, 3), 5)\n"
                "    def test_negative(self):\n        self.assertEqual(add(-2, 3), 1)\n"
            )
            config = {"verify_profiles": {"fixture": {
                "argv": [sys.executable, "-B", "-m", "unittest", "discover", "-q"],
                "cwd": ".", "timeout_sec": 30,
            }}}
            with patch.dict(os.environ, environment), patch.object(feature, "agent_config", return_value=config):
                self.assertTrue(handoff.validate("planner", "reviewer", "fix/addition", root=project)["passed"])
                self.assertFalse(handoff.validate("planner", "backend", "fix/addition", root=project)["passed"])
                # Simulate a reviewer's approval in the isolated fixture, not a live artifact.
                work.write_text(work.read_text().replace("status: draft", "status: approved"))
                self.assertTrue(handoff.validate("planner", "backend", "fix/addition", root=project)["passed"])
                failed = handoff.validate("backend", "reviewer", "fix/addition", root=project, verify_profile="fixture")
                self.assertFalse(failed["passed"])
                self.assertEqual(failed["verification_status"], "failed")
                review = work.with_name("REVIEW.md")
                review.write_text("---\nagent: reviewer\nfeature: fix/addition\nstatus: rejected\n"
                                  "created: 2026-09-13\nupdated: 2026-09-13\n---\n# Incorrect addition\n")
                self.assertTrue(handoff.validate("reviewer", "backend", "fix/addition", root=project)["passed"])
                source.write_text("def add(a, b):\n    return a + b\n")
                work.write_text(work.read_text().replace("status: approved", "status: draft"))
                checked = feature.gate_check("fix/addition", root=project, verify=True, verify_profile="fixture")
                self.assertEqual(checked["verification_status"], "passed")
                work.write_text(work.read_text().replace("status: draft", "status: approved"))
                review.write_text(review.read_text().replace("status: rejected", "status: approved"))
                completed = handoff.validate("reviewer", "qa", "fix/addition", root=project, verify_profile="fixture")
                self.assertTrue(completed["passed"], completed)
                self.assertEqual(completed["verification_status"], "passed")
                self.assertEqual(feature.list_artifacts("fix/addition", root=project)["count"], 2)
