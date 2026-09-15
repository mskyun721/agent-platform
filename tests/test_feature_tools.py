from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server" / "src"))


FRONTMATTER = (
    "---\n"
    "agent: {agent}\n"
    "feature: {feature}\n"
    "status: {status}\n"
    "created: 2026-07-01\n"
    "updated: 2026-07-01\n"
    "---\n\n"
    "# body\n"
)


class ActiveProjectTestCase(unittest.TestCase):
    """Base: points .active-project at a temp target and restores it after."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.target = Path(self.temp_dir.name) / "target"
        self.target.mkdir()
        self.active_project = ROOT / ".active-project"
        self.previous_active = (
            self.active_project.read_text(encoding="utf-8")
            if self.active_project.is_file()
            else None
        )
        self.active_project.write_text(str(self.target) + "\n", encoding="utf-8")
        self.env = patch.dict(
            os.environ,
            {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(self.target)},
        )
        self.env.start()
        os.environ.pop("TARGET_PROJECT_ROOT", None)
        self.resolved_target = self.target.resolve()
        # P9: backend/reviewer handoffs require the target's own ARCHITECTURE.md.
        (self.resolved_target / "ARCHITECTURE.md").write_text("# Structure\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.env.stop()
        if self.previous_active is None:
            self.active_project.unlink(missing_ok=True)
        else:
            self.active_project.write_text(self.previous_active, encoding="utf-8")
        self.temp_dir.cleanup()

    def write_artifact(
        self,
        feature: str,
        fname: str,
        agent: str = "planner",
        status: str = "approved",
    ) -> Path:
        subpath = feature if "/" in feature else f"features/{feature}"
        fdir = self.resolved_target / "docs" / subpath
        fdir.mkdir(parents=True, exist_ok=True)
        path = fdir / fname
        path.write_text(
            FRONTMATTER.format(agent=agent, feature=feature, status=status),
            encoding="utf-8",
        )
        return path

    def write_drawio(self, feature: str) -> Path:
        """Full-track planning now includes FLOW.drawio (P7); copy the template."""
        subpath = feature if "/" in feature else f"features/{feature}"
        fdir = self.resolved_target / "docs" / subpath
        fdir.mkdir(parents=True, exist_ok=True)
        path = fdir / "FLOW.drawio"
        path.write_text((ROOT / "templates" / "FLOW.drawio").read_text(encoding="utf-8"), encoding="utf-8")
        return path


class DocsRootRequiresActiveProjectTest(ActiveProjectTestCase):
    """docs_root must fail loudly instead of silently writing into agent-platform."""

    def _clear_active_project(self) -> None:
        self.active_project.unlink(missing_ok=True)

    def test_docs_root_raises_without_active_project(self) -> None:
        from agent_platform_mcp import config

        self._clear_active_project()
        with self.assertRaises(RuntimeError):
            config.docs_root()

    def test_scaffold_raises_without_active_project(self) -> None:
        from agent_platform_mcp.tools import feature

        self._clear_active_project()
        with self.assertRaises(RuntimeError):
            feature.scaffold("payment-cancel")
        self.assertFalse((ROOT / "docs" / "features" / "payment-cancel").exists())

    def test_docs_root_uses_explicit_project_dir(self) -> None:
        from agent_platform_mcp import config

        self._clear_active_project()
        self.assertEqual(config.docs_root(self.target), self.target)


class ScaffoldTest(ActiveProjectTestCase):
    def test_scaffold_creates_prd_and_task_in_target_project(self) -> None:
        from agent_platform_mcp.tools import feature

        result = feature.scaffold("payment-cancel")

        fdir = self.resolved_target / "docs" / "features" / "payment-cancel"
        self.assertTrue((fdir / "PRD.md").is_file())
        self.assertTrue((fdir / "TASK.md").is_file())
        self.assertEqual(result["feature"], "payment-cancel")
        prd = (fdir / "PRD.md").read_text(encoding="utf-8")
        self.assertIn("feature: payment-cancel", prd)
        self.assertNotIn("<feature-name>", prd)
        self.assertNotIn("YYYY-MM-DD", prd)

    def test_scaffold_type_prefixed_name_goes_to_docs_type_dir(self) -> None:
        from agent_platform_mcp.tools import feature

        feature.scaffold("fix/login-bug")

        fdir = self.resolved_target / "docs" / "fix" / "login-bug"
        self.assertTrue((fdir / "PRD.md").is_file())
        self.assertFalse(
            (self.resolved_target / "docs" / "features" / "fix").exists()
        )

    def test_scaffold_rejects_existing_directory(self) -> None:
        from agent_platform_mcp.tools import feature

        feature.scaffold("payment-cancel")
        with self.assertRaises(FileExistsError):
            feature.scaffold("payment-cancel")

    def test_scaffold_rejects_unsafe_names(self) -> None:
        from agent_platform_mcp.tools import feature

        for bad in ("../escape", "UPPER", "a", "has space", "trailing/"):
            with self.assertRaises(ValueError, msg=bad):
                feature.scaffold(bad)


class GateCheckTest(ActiveProjectTestCase):
    def test_gate_check_passes_with_valid_frontmatter(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("pay", "PRD.md")
        self.write_artifact("pay", "TASK.md")

        result = feature.gate_check("pay")

        self.assertTrue(result["passed"])
        self.assertEqual(len(result["files"]), 2)

    def test_gate_check_reports_missing_frontmatter_fields(self) -> None:
        from agent_platform_mcp.tools import feature

        fdir = self.resolved_target / "docs" / "features" / "pay"
        fdir.mkdir(parents=True)
        (fdir / "PRD.md").write_text(
            "---\nagent: planner\n---\n\n# no feature/status/dates\n",
            encoding="utf-8",
        )

        result = feature.gate_check("pay")

        self.assertFalse(result["passed"])
        errors = result["files"][0]["errors"]
        self.assertTrue(any("feature" in e for e in errors))
        self.assertTrue(any("status" in e for e in errors))

    def test_gate_check_rejects_invalid_agent_and_status(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("pay", "PRD.md", agent="hacker", status="shipped")

        result = feature.gate_check("pay")

        self.assertFalse(result["passed"])
        errors = result["files"][0]["errors"]
        self.assertTrue(any("invalid agent" in e for e in errors))
        self.assertTrue(any("invalid status" in e for e in errors))

    def test_agent_gate_requires_approved_prerequisites(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("pay", "PRD.md", status="approved")
        self.write_artifact("pay", "TASK.md", status="draft")
        self.write_drawio("pay")

        result = feature.gate_check("pay", agent="backend")

        self.assertFalse(result["passed"])
        gate = result["agent_gate"]
        self.assertEqual(gate["missing"], [])
        self.assertIn("TASK.md (status=draft)", gate["not_approved"])

    def test_agent_gate_reports_missing_prerequisites(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("pay", "PRD.md")

        result = feature.gate_check("pay", agent="backend")

        self.assertFalse(result["passed"])
        self.assertIn("TASK.md", result["agent_gate"]["missing"])

    def test_agent_gate_passes_when_all_prerequisites_approved(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("pay", "PRD.md")
        self.write_artifact("pay", "TASK.md")
        self.write_drawio("pay")

        result = feature.gate_check("pay", agent="backend")

        self.assertTrue(result["passed"])
        self.assertTrue(result["agent_gate"]["passed"])

    def test_gate_check_unknown_agent_raises(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("pay", "PRD.md")
        with self.assertRaises(ValueError):
            feature.gate_check("pay", agent="devops")


class LightTrackGateTest(ActiveProjectTestCase):
    def test_fix_track_uses_light_prerequisites(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("fix/login-bug", "PRD.md", status="approved")
        result = feature.gate_check("fix/login-bug", agent="reviewer")
        self.assertEqual(result["track"], "light")
        # light 트랙 reviewer는 PRD.md만 요구 — API-SPEC/DECISIONS 없어도 통과
        self.assertTrue(result["passed"])

    def test_feature_track_stays_full(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("pay", "PRD.md", status="approved")
        result = feature.gate_check("pay", agent="reviewer")
        self.assertEqual(result["track"], "full")
        self.assertFalse(result["passed"])  # API-SPEC.md, DECISIONS.md 누락


class GateVerifyTest(ActiveProjectTestCase):
    def test_verify_runs_configured_command_and_gates_on_exit_code(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("fix/login-bug", "PRD.md", status="approved")
        with patch("agent_platform_mcp.tools.feature._gate_verify_command", return_value="false"):
            result = feature.gate_check("fix/login-bug", agent="reviewer", verify=True)
        self.assertEqual(result["verify_exit_code"], 1)
        self.assertFalse(result["passed"])

    def test_verify_pass_keeps_gate_open(self) -> None:
        from agent_platform_mcp.tools import feature

        self.write_artifact("fix/login-bug", "PRD.md", status="approved")
        with patch("agent_platform_mcp.tools.feature._gate_verify_command", return_value="true"):
            result = feature.gate_check("fix/login-bug", agent="reviewer", verify=True)
        self.assertEqual(result["verify_exit_code"], 0)
        self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()
