from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server" / "src"))


class AgentRunnerDryRunTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.target = Path(self.temp_dir.name) / "target"
        self.feature_dir = self.target / "docs" / "features" / "payment-cancel"
        self.feature_dir.mkdir(parents=True)
        for fname in ("PRD.md", "TASK.md"):
            (self.feature_dir / fname).write_text(
                "---\n"
                "agent: planner\n"
                "feature: payment-cancel\n"
                "status: approved\n"
                "created: 2026-05-06\n"
                "updated: 2026-05-06\n"
                "---\n\n"
                f"# {fname}\n",
                encoding="utf-8",
            )
        self.active_project = ROOT / ".active-project"
        self.previous_active = (
            self.active_project.read_text(encoding="utf-8")
            if self.active_project.is_file()
            else None
        )
        self.active_project.write_text(str(self.target) + "\n", encoding="utf-8")
        self.resolved_target = self.target.resolve()
        self.resolved_feature_dir = (
            self.resolved_target / "docs" / "features" / "payment-cancel"
        )

    def tearDown(self) -> None:
        if self.previous_active is None:
            self.active_project.unlink(missing_ok=True)
        else:
            self.active_project.write_text(self.previous_active, encoding="utf-8")
        self.temp_dir.cleanup()

    def test_backend_codex_dry_run_uses_target_project_as_workdir(self) -> None:
        from agent_platform_mcp.tools import backend

        result = backend.run_codex("payment-cancel", dry_run=True)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["command"][:3], ["codex", "exec", "--cd"])
        self.assertEqual(result["command"][3], str(self.resolved_target))
        self.assertIn(str(self.resolved_feature_dir / "API-SPEC.md"), result["expected_outputs"])
        self.assertIn(str(self.resolved_feature_dir / "DECISIONS.md"), result["expected_outputs"])
        self.assertIn("TARGET_PROJECT", result["prompt_preview"])

    def test_backend_gemini_dry_run_uses_auto_edit(self) -> None:
        from agent_platform_mcp.tools import backend

        result = backend.run_gemini("payment-cancel", dry_run=True)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["command"][:3], ["gemini", "--approval-mode", "auto_edit"])
        self.assertIn(str(self.resolved_target), result["prompt_preview"])

    def test_agent_cli_routes_backend_dry_run(self) -> None:
        from agent_platform_mcp import cli

        with redirect_stdout(StringIO()):
            exit_code = cli.main(
                ["run", "backend", "payment-cancel", "--ai", "codex", "--dry-run"]
            )

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
