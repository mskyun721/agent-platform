"""P7 Task A3: FLOW.drawio is a machine-readable planning artifact checked by the gate."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server/src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_feature_tools import ActiveProjectTestCase  # noqa: E402

VALID_DRAWIO = (ROOT / "templates" / "FLOW.drawio").read_text(encoding="utf-8")
BROKEN_DRAWIO = (
    '<mxfile><diagram><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    '<mxCell id="a" vertex="1" parent="1"/>'
    '<mxCell id="e" edge="1" parent="1" source="a" target="ghost"/>'
    "</root></mxGraphModel></diagram></mxfile>"
)


class DrawioGateTest(ActiveProjectTestCase):
    def _drawio(self, feature: str, text: str = VALID_DRAWIO) -> Path:
        subpath = feature if "/" in feature else f"features/{feature}"
        fdir = self.resolved_target / "docs" / subpath
        fdir.mkdir(parents=True, exist_ok=True)
        path = fdir / "FLOW.drawio"
        path.write_text(text, encoding="utf-8")
        return path

    def _entry(self, result: dict, name: str = "FLOW.drawio") -> dict:
        return next(f for f in result["files"] if f["file"] == name)

    def test_valid_drawio_is_listed_and_passes(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("pay", "PRD.md")
        self.write_artifact("pay", "TASK.md")
        self._drawio("pay")

        result = feature.gate_check("pay")

        entry = self._entry(result)
        self.assertEqual(entry["kind"], "drawio")
        self.assertTrue(entry["passed"], entry)
        self.assertEqual(entry["errors"], [])
        self.assertEqual(result["artifact_status"], "passed")

    def test_broken_drawio_fails_artifact_status(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("pay", "PRD.md")
        self._drawio("pay", BROKEN_DRAWIO)

        result = feature.gate_check("pay")

        entry = self._entry(result)
        self.assertFalse(entry["passed"])
        self.assertTrue(entry["errors"], "validator findings must surface as errors")
        self.assertEqual(result["artifact_status"], "failed")
        self.assertFalse(result["passed"])

    def test_unparseable_drawio_is_an_error_not_a_crash(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("pay", "PRD.md")
        self._drawio("pay", "not xml at all")

        entry = self._entry(feature.gate_check("pay"))

        self.assertFalse(entry["passed"])
        self.assertTrue(any("parse" in e.lower() or "xml" in e.lower() for e in entry["errors"]), entry["errors"])

    def test_full_track_backend_handoff_requires_flow_drawio(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("pay", "PRD.md")
        self.write_artifact("pay", "TASK.md")

        without = feature.gate_check("pay", agent="backend")
        self._drawio("pay")
        with_flow = feature.gate_check("pay", agent="backend")

        self.assertIn("FLOW.drawio", without["agent_gate"]["missing"])
        self.assertFalse(without["passed"])
        self.assertTrue(with_flow["agent_gate"]["passed"], with_flow["agent_gate"])
        self.assertTrue(with_flow["passed"], with_flow)

    def test_drawio_has_no_status_and_is_not_checked_for_approval(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("pay", "PRD.md")
        self.write_artifact("pay", "TASK.md")
        self._drawio("pay")

        result = feature.gate_check("pay", agent="backend")

        self.assertEqual(result["agent_gate"]["not_approved"], [])
        self.assertIsNone(self._entry(result)["status"])

    def test_light_and_work_tracks_do_not_require_flow_drawio(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("fix/bug", "PRD.md")

        result = feature.gate_check("fix/bug", agent="backend")

        self.assertEqual(result["agent_gate"]["missing"], [])
        self.assertTrue(result["passed"], result)

    def test_list_artifacts_includes_drawio(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("pay", "PRD.md")
        self._drawio("pay")

        items = {a["file"]: a for a in feature.list_artifacts("pay")["artifacts"]}

        self.assertIn("FLOW.drawio", items)
        self.assertFalse(items["FLOW.drawio"]["has_frontmatter"])
        self.assertEqual(items["FLOW.drawio"]["kind"], "drawio")

    def test_missing_validator_is_reported_not_ignored(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("pay", "PRD.md")
        self._drawio("pay")
        with patch("agent_platform_mcp.tools.feature.DRAWIO_VALIDATOR", self.resolved_target / "nope" / "validate.py"):
            entry = self._entry(feature.gate_check("pay"))

        self.assertFalse(entry["passed"])
        self.assertTrue(any("validator" in e for e in entry["errors"]), entry["errors"])


if __name__ == "__main__":
    unittest.main()
