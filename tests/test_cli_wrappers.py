"""Characterization tests locking CLI-wrapper behavior across tool modules."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server" / "src"))

from test_feature_tools import ActiveProjectTestCase  # noqa: E402


def _completed(cmd: list[str], stdout: str = "# output\n") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=stdout, stderr="")


class GeminiCommandShapeTest(ActiveProjectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_artifact("pay", "PRD.md")
        self.write_artifact("pay", "TASK.md")

    def test_readonly_agents_use_plan_approval_mode(self) -> None:
        from agent_platform_mcp.tools import audit, plan, qa, review

        results = [
            plan.run_gemini("pay", requirements="결제 취소", dry_run=True),
            review.run_gemini("pay", dry_run=True),
            audit.run_gemini("pay", dry_run=True),
            qa.run_gemini("pay", dry_run=True),
        ]
        for result in results:
            self.assertEqual(result["command"][:3], ["gemini", "--approval-mode", "plan"])
            self.assertEqual(result["command"][3], "-p")

    def test_release_gemini_uses_model_and_auto_edit(self) -> None:
        from agent_platform_mcp.tools import release

        result = release.run_gemini("pay", dry_run=True)

        self.assertEqual(
            result["command"][:5],
            ["gemini", "-m", "gemini-2.5-flash", "--approval-mode", "auto_edit"],
        )


class SubprocessOutputHandlingTest(ActiveProjectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_artifact("pay", "PRD.md")
        self.write_artifact("pay", "TASK.md")
        self.feature_dir = self.resolved_target / "docs" / "features" / "pay"

    def test_review_codex_writes_review_md_with_draft_frontmatter(self) -> None:
        from agent_platform_mcp.tools import review

        with (
            patch("shutil.which", return_value="/usr/bin/codex"),
            patch(
                "subprocess.run",
                return_value=_completed([], stdout="# REVIEW: pay\n\nfindings"),
            ),
        ):
            result = review.run_codex("pay")

        content = (self.feature_dir / "REVIEW.md").read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\nagent: reviewer\n"))
        self.assertIn("status: draft", content)
        self.assertIn("ai_backend: codex", content)
        self.assertIn("# REVIEW: pay", content)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["output_path"], str(self.feature_dir / "REVIEW.md"))

    def test_audit_gemini_writes_security_audit_md(self) -> None:
        from agent_platform_mcp.tools import audit

        with (
            patch("shutil.which", return_value="/usr/bin/gemini"),
            patch("subprocess.run", return_value=_completed([], stdout="# audit")),
        ):
            audit.run_gemini("pay")

        content = (self.feature_dir / "SECURITY-AUDIT.md").read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\nagent: security\n"))
        self.assertIn("tool: gemini", content)
        self.assertIn("# audit", content)

    def test_plan_codex_patches_missing_frontmatter_on_artifacts(self) -> None:
        from agent_platform_mcp.tools import plan

        (self.feature_dir / "PRD.md").write_text("# PRD without fm\n", encoding="utf-8")
        (self.feature_dir / "TASK.md").write_text("# TASK without fm\n", encoding="utf-8")

        with (
            patch("shutil.which", return_value="/usr/bin/codex"),
            patch("subprocess.run", return_value=_completed([])),
        ):
            result = plan.run_codex("pay", requirements="결제 취소")

        prd = (self.feature_dir / "PRD.md").read_text(encoding="utf-8")
        self.assertTrue(prd.startswith("---\nagent: planner\n"))
        self.assertIn("tool: codex", prd)
        self.assertEqual(len(result["artifacts"]), 2)

    def test_timeout_raises_runtime_error(self) -> None:
        from agent_platform_mcp.tools import review

        with (
            patch("shutil.which", return_value="/usr/bin/codex"),
            patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="codex", timeout=1),
            ),
        ):
            with self.assertRaises(RuntimeError):
                review.run_codex("pay", timeout_sec=1)

    def test_missing_cli_raises_runtime_error(self) -> None:
        from agent_platform_mcp.tools import review

        with patch("shutil.which", return_value=None):
            with self.assertRaises(RuntimeError):
                review.run_codex("pay")


if __name__ == "__main__":
    unittest.main()
