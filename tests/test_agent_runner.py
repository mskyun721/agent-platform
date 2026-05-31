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
        self.fix_feature_dir = (
            self.target / "docs" / "features" / "fix" / "certificate-manager-db"
        )
        self.fix_feature_dir.mkdir(parents=True)
        for fname in ("PRD.md", "API-SPEC.md", "DECISIONS.md"):
            (self.fix_feature_dir / fname).write_text(
                "---\n"
                "agent: planner\n"
                "feature: fix/certificate-manager-db\n"
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

    def test_review_codex_dry_run_accepts_nested_fix_feature(self) -> None:
        from agent_platform_mcp.tools import review

        result = review.run_codex("fix/certificate-manager-db", dry_run=True)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["feature"], "fix/certificate-manager-db")
        self.assertEqual(
            result["output_path"],
            str(self.resolved_target / "docs" / "features" / "fix" / "certificate-manager-db" / "REVIEW.md"),
        )

    def test_review_prompt_uses_backend_neutral_output_format(self) -> None:
        from agent_platform_mcp.tools import review

        result = review.run_codex("payment-cancel", dry_run=True)

        prompt = result["command"][-1]
        self.assertIn("# REVIEW: payment-cancel", prompt)
        self.assertIn("## 1. Summary", prompt)
        self.assertIn("## 2. Findings", prompt)
        self.assertIn("특정 AI 제품명이나 실행 CLI 이름을 본문에 쓰지 말고", prompt)
        self.assertNotIn("Codex 원문", prompt)

    def test_review_template_is_backend_neutral(self) -> None:
        template = (ROOT / "templates" / "REVIEW.md").read_text(encoding="utf-8")

        self.assertIn("ai_backend: <ai-backend>", template)
        self.assertIn("## 1. Summary", template)
        self.assertIn("## 2. Findings", template)
        self.assertNotIn("tool: codex", template)
        self.assertNotIn("review_run_codex", template)
        self.assertNotIn("Codex 원문", template)


if __name__ == "__main__":
    unittest.main()
