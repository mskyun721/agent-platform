"""P9: roles reference the target's own ARCHITECTURE.md instead of a fixed hexagonal standard."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server/src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_feature_tools import ActiveProjectTestCase  # noqa: E402


class StructureGateTest(ActiveProjectTestCase):
    def _full_planning(self, feature: str = "pay") -> None:
        self.write_artifact(feature, "PRD.md")
        self.write_artifact(feature, "TASK.md")
        self.write_drawio(feature)

    def test_gate_reports_structure_present(self) -> None:
        from agent_platform_mcp.tools import feature

        self._full_planning()
        result = feature.gate_check("pay")

        self.assertEqual(result["structure"], {"path": "ARCHITECTURE.md", "status": "present"})

    def test_backend_handoff_requires_structure_doc(self) -> None:
        from agent_platform_mcp.tools import feature

        self._full_planning()
        (self.resolved_target / "ARCHITECTURE.md").unlink()

        result = feature.gate_check("pay", agent="backend")

        self.assertEqual(result["structure"]["status"], "missing")
        self.assertIn("ARCHITECTURE.md (project root)", result["agent_gate"]["missing"])
        self.assertFalse(result["passed"])

    def test_reviewer_handoff_requires_structure_doc_on_light_track(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("fix/typo", "PRD.md")
        (self.resolved_target / "ARCHITECTURE.md").unlink()

        result = feature.gate_check("fix/typo", agent="reviewer")

        self.assertIn("ARCHITECTURE.md (project root)", result["agent_gate"]["missing"])
        self.assertFalse(result["passed"])

    def test_planner_handoff_ignores_structure_doc(self) -> None:
        from agent_platform_mcp.tools import feature

        self._full_planning()
        (self.resolved_target / "ARCHITECTURE.md").unlink()

        result = feature.gate_check("pay", agent="planner")

        self.assertEqual(result["agent_gate"]["missing"], [])
        self.assertTrue(result["agent_gate"]["passed"])


class ReviewFocusTest(unittest.TestCase):
    def test_structure_focus_points_at_target_architecture_doc(self) -> None:
        from agent_platform_mcp.tools import review, runner

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "docs" / "features" / "pay").mkdir(parents=True)
            context = runner.ProjectContext(path=root, project_id=None, verify_profile_id=None)
            prompt = review._build_prompt("pay", "structure", context)

        self.assertIn("ARCHITECTURE.md", prompt)
        self.assertNotIn("hexagonal", review.VALID_FOCUS)
        self.assertIn("structure", review.VALID_FOCUS)


class ContextBlockStructureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.item = self.root / "docs" / "features" / "example"
        self.item.mkdir(parents=True)
        (self.item / "PRD.md").write_text("---\nstatus: draft\n---\n# Req\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_structure_doc_is_announced_without_body(self) -> None:
        from agent_platform_mcp.tools import runner

        doc = self.root / "ARCHITECTURE.md"
        doc.write_text("# Structure\nsecret-rule-body\n")

        block, sources = runner.context_block("example", self.root)

        self.assertIn('"structure": "ARCHITECTURE.md"', block)
        self.assertNotIn("secret-rule-body", block)
        self.assertIn(str(doc), sources)

    def test_missing_structure_doc_is_reported(self) -> None:
        from agent_platform_mcp.tools import runner

        block, _ = runner.context_block("example", self.root)

        self.assertIn('"structure": "ARCHITECTURE.md"', block)
        self.assertIn('"status": "missing"', block)


if __name__ == "__main__":
    unittest.main()
