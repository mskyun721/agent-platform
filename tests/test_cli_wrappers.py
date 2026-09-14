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


class CodexCommandShapeTest(ActiveProjectTestCase):
    """codex is the only external CLI (P1 Task 2: Gemini removed)."""

    def setUp(self) -> None:
        super().setUp()
        self.write_artifact("pay", "PRD.md")
        self.write_artifact("pay", "TASK.md")

    def test_all_wrappers_dry_run_with_codex_exec(self) -> None:
        from agent_platform_mcp.tools import audit, plan, qa, release, review

        results = [
            plan.run("pay", requirements="결제 취소", cli="codex", dry_run=True),
            review.run("pay", cli="codex", dry_run=True),
            audit.run("pay", cli="codex", dry_run=True),
            qa.run("pay", cli="codex", dry_run=True),
            release.run("pay", cli="codex", dry_run=True),
        ]
        for result in results:
            self.assertEqual(result["command"][:3], ["codex", "exec", "--cd"])
            self.assertIn("--sandbox", result["command"])
            self.assertEqual(result["command"][result["command"].index("--sandbox") + 1], "workspace-write")
            self.assertNotIn("--full-auto", result["command"])

    def test_release_passes_model_to_codex(self) -> None:
        from agent_platform_mcp.tools import release

        result = release.run("pay", cli="codex", model="gpt-5-codex", dry_run=True)

        cmd = result["command"]
        self.assertEqual(cmd[cmd.index("-m") + 1], "gpt-5-codex")
        self.assertEqual(result["model"], "gpt-5-codex")

    def test_release_without_model_has_no_model_flag(self) -> None:
        from agent_platform_mcp.tools import release

        result = release.run("pay", cli="codex", dry_run=True)

        self.assertNotIn("-m", result["command"])
        self.assertNotIn("model", result)

    def test_wrappers_reject_gemini(self) -> None:
        from agent_platform_mcp.tools import audit, backend, plan, qa, release, review

        for fn in (plan.run, review.run, audit.run, qa.run, release.run, backend.run):
            with self.subTest(fn=fn.__module__):
                kwargs = {"requirements": "x"} if fn is plan.run else {}
                with self.assertRaises(ValueError):
                    fn("pay", cli="gemini", dry_run=True, **kwargs)


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
            result = review.run("pay", cli="codex")

        content = (self.feature_dir / "REVIEW.md").read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\nagent: reviewer\n"))
        self.assertIn("status: draft", content)
        self.assertIn("ai_backend: codex", content)
        self.assertIn("# REVIEW: pay", content)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["output_path"], str(self.feature_dir / "REVIEW.md"))

    def test_audit_codex_writes_security_audit_md(self) -> None:
        from agent_platform_mcp.tools import audit

        with (
            patch("shutil.which", return_value="/usr/bin/codex"),
            patch("subprocess.run", return_value=_completed([], stdout="# audit")),
        ):
            audit.run("pay", cli="codex")

        content = (self.feature_dir / "SECURITY-AUDIT.md").read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\nagent: security\n"))
        self.assertIn("tool: codex", content)
        self.assertIn("# audit", content)

    def test_plan_codex_patches_missing_frontmatter_on_artifacts(self) -> None:
        from agent_platform_mcp.tools import plan

        (self.feature_dir / "PRD.md").write_text("# PRD without fm\n", encoding="utf-8")
        (self.feature_dir / "TASK.md").write_text("# TASK without fm\n", encoding="utf-8")

        with (
            patch("shutil.which", return_value="/usr/bin/codex"),
            patch("subprocess.run", return_value=_completed([])),
        ):
            result = plan.run("pay", requirements="결제 취소", cli="codex")

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
                review.run("pay", cli="codex", timeout_sec=1)

    def test_missing_cli_raises_runtime_error(self) -> None:
        from agent_platform_mcp.tools import review

        with patch("shutil.which", return_value=None):
            with self.assertRaises(RuntimeError):
                review.run("pay", cli="codex")


class UnifiedRunEntrypointTest(ActiveProjectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_artifact("pay", "PRD.md")
        self.write_artifact("pay", "TASK.md")

    def test_suffix_wrappers_are_removed(self) -> None:
        from agent_platform_mcp.tools import audit, backend, plan, qa, release, review

        for mod in (plan, backend, review, audit, qa, release):
            self.assertFalse(hasattr(mod, "run_gemini"), mod.__name__)
            self.assertFalse(hasattr(mod, "run_codex"), mod.__name__)
            self.assertTrue(hasattr(mod, "run"), mod.__name__)

    def test_invalid_cli_raises(self) -> None:
        from agent_platform_mcp.tools import review

        with self.assertRaises(ValueError):
            review.run("pay", cli="gpt", dry_run=True)

    def test_auto_uses_preferred_cli(self) -> None:
        from agent_platform_mcp.tools import review

        result = review.run("pay", cli="auto", dry_run=True)
        # preferred_cli()가 codex이므로 codex exec 커맨드여야 한다
        self.assertEqual(result["command"][0], "codex")


if __name__ == "__main__":
    unittest.main()
