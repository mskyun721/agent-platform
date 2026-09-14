"""P1 Task 4: declared risk is cross-checked against changed paths."""

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

from agent_platform_mcp.tools import feature  # noqa: E402

RULES = {"paths": ["**/auth/**", "**/migration/**"]}


class RiskCrossCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        env = patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        rules = patch("agent_platform_mcp.tools.feature.risk_rules", return_value=RULES)
        rules.start()
        self.addCleanup(rules.stop)
        self.name = "refactor/small-change"

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
            cwd=str(self.root), check=True, capture_output=True,
        )

    def _work(self, risk: str, reason: str = "") -> None:
        feature.scaffold(self.name, root=self.root, contract="work-v1")
        path = self.root / "docs" / self.name / "WORK.md"
        text = path.read_text(encoding="utf-8")
        text = text.replace("status: draft", "status: approved").replace("risk: undecided", f"risk: {risk}")
        if reason:
            text = text.replace("risk_reason:", f"risk_reason: {reason}")
        path.write_text(text, encoding="utf-8")

    def _touch(self, *rels: str) -> None:
        for rel in rels:
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x", encoding="utf-8")

    def test_low_declared_but_auth_path_touched_is_conflict(self) -> None:
        self._git("init", "-q")
        self._work("low")
        self._touch("src/main/kotlin/auth/Token.kt")

        result = feature.gate_check(self.name, root=self.root)

        self.assertEqual(result["risk"]["status"], "conflict")
        self.assertEqual(result["risk"]["path_hits"], ["src/main/kotlin/auth/Token.kt"])
        self.assertFalse(result["passed"])

    def test_high_declared_with_reason_and_auth_path_is_ok(self) -> None:
        self._git("init", "-q")
        self._work("high", reason="token rotation")
        self._touch("src/main/kotlin/auth/Token.kt")

        result = feature.gate_check(self.name, root=self.root)

        self.assertEqual(result["risk"]["status"], "ok")
        self.assertEqual(result["risk"]["declared"], "high")
        self.assertTrue(result["passed"], result["files"])

    def test_low_with_no_risky_paths_is_ok(self) -> None:
        self._git("init", "-q")
        self._work("low")
        self._touch("src/main/kotlin/util/Str.kt")

        result = feature.gate_check(self.name, root=self.root)

        self.assertEqual(result["risk"]["status"], "ok")
        self.assertEqual(result["risk"]["path_hits"], [])
        self.assertTrue(result["passed"], result["files"])

    def test_committed_changes_are_not_counted_only_pending_ones(self) -> None:
        self._git("init", "-q")
        self._touch("src/main/kotlin/auth/Old.kt")
        self._git("add", ".")
        self._git("commit", "-qm", "base")
        self._work("low")

        result = feature.gate_check(self.name, root=self.root)

        self.assertEqual(result["risk"]["path_hits"], [])
        self.assertEqual(result["risk"]["status"], "ok")

    def test_legacy_contract_without_declaration_is_undeclared_and_not_blocked(self) -> None:
        self._git("init", "-q")
        feature.scaffold(self.name, root=self.root)  # PRD + TASK, no risk field
        self._touch("src/main/kotlin/auth/Token.kt")

        result = feature.gate_check(self.name, root=self.root)

        self.assertEqual(result["risk"]["status"], "undeclared")
        self.assertEqual(result["risk"]["path_hits"], ["src/main/kotlin/auth/Token.kt"])
        self.assertEqual(result["artifact_status"], "passed")
        self.assertTrue(result["passed"], "legacy documents are never auto-downgraded or blocked")

    def test_low_outside_git_is_unverified_not_ok(self) -> None:
        self._work("low")

        result = feature.gate_check(self.name, root=self.root)

        self.assertEqual(result["risk"]["status"], "unverified")
        self.assertIsNone(result["risk"]["path_hits"])
        self.assertFalse(result["passed"])

    def test_no_rules_configured_is_unverified(self) -> None:
        self._git("init", "-q")
        self._work("low")
        self._touch("src/main/kotlin/auth/Token.kt")
        with patch("agent_platform_mcp.tools.feature.risk_rules", return_value={"paths": []}):
            result = feature.gate_check(self.name, root=self.root)

        self.assertEqual(result["risk"]["status"], "unverified")
        self.assertFalse(result["passed"])


    def test_staged_file_on_unborn_branch_is_included(self) -> None:
        self._git("init", "-q")
        self._work("low")
        self._touch("src/auth/Staged.kt")
        self._git("add", "src")
        self.assertEqual(feature.gate_check(self.name, root=self.root)["risk"]["path_hits"], ["src/auth/Staged.kt"])

    def test_root_and_unusual_paths_are_not_git_quoted(self) -> None:
        self._git("init", "-q")
        self._work("low")
        paths = ["auth/토큰 file.kt", "src/auth/new\nline.kt"]
        self._touch(*paths)
        self.assertEqual(feature.gate_check(self.name, root=self.root)["risk"]["path_hits"], sorted(paths))

    def test_branch_base_catches_committed_change(self) -> None:
        self._git("init", "-q")
        self._touch("ordinary.txt")
        self._git("add", ".")
        self._git("commit", "-qm", "base")
        self._git("tag", "risk-baseline")
        self._touch("src/auth/Committed.kt")
        self._git("add", ".")
        self._git("commit", "-qm", "auth change")
        self._work("low")
        result = feature.gate_check(self.name, root=self.root, risk_base="risk-baseline")
        self.assertFalse(result["passed"])
        self.assertEqual(result["risk"]["scope"], "branch-and-pending")
        self.assertEqual(result["risk"]["path_hits"], ["src/auth/Committed.kt"])
        self.assertTrue(result["risk"]["comparison_revision"])

    def test_rename_keeps_original_risky_path(self) -> None:
        self._git("init", "-q")
        self._touch("src/auth/Token.kt")
        self._git("add", ".")
        self._git("commit", "-qm", "base")
        self._git("mv", "src/auth/Token.kt", "Token.kt")
        self._work("low")
        self.assertEqual(feature.gate_check(self.name, root=self.root)["risk"]["path_hits"], ["src/auth/Token.kt"])

    def test_staged_change_reverted_in_worktree_still_counts(self) -> None:
        self._git("init", "-q")
        self._touch("src/auth/Token.kt")
        self._git("add", ".")
        self._git("commit", "-qm", "base")
        path = self.root / "src/auth/Token.kt"
        path.write_text("changed", encoding="utf-8")
        self._git("add", ".")
        path.write_text("x", encoding="utf-8")
        self._work("low")
        self.assertFalse(feature.gate_check(self.name, root=self.root)["passed"])

    def test_invalid_base_blocks_instead_of_falling_back(self) -> None:
        self._git("init", "-q")
        self._work("low")
        result = feature.gate_check(self.name, root=self.root, risk_base="missing-revision")
        self.assertFalse(result["passed"])
        self.assertEqual(result["risk"]["status"], "unverified")

    def test_requested_invalid_base_also_blocks_legacy_contract(self) -> None:
        self._git("init", "-q")
        feature.scaffold(self.name, root=self.root)
        result = feature.gate_check(self.name, root=self.root, risk_base="missing-revision")
        self.assertFalse(result["passed"])
        self.assertEqual(result["risk"]["status"], "unverified")

    def test_git_errors_and_timeouts_block_declared_risk(self) -> None:
        self._work("high", "database write")
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("git", 10), ValueError("git diff failed")):
            with self.subTest(error=type(error).__name__), patch.object(feature, "_git_output", side_effect=error):
                result = feature.gate_check(self.name, root=self.root)
                self.assertFalse(result["passed"])
                self.assertEqual(result["risk"]["status"], "unverified")

    def test_invalid_risk_does_not_crash(self) -> None:
        self._git("init", "-q")
        self._work("")
        result = feature.gate_check(self.name, root=self.root)
        self.assertFalse(result["passed"])
        self.assertEqual(result["risk"]["status"], "invalid")

    def test_high_legacy_declaration_requires_security_for_qa(self) -> None:
        self._git("init", "-q")
        self.name = "fix/small-change"
        self._work("high", "authorization")
        work = self.root / "docs" / self.name / "WORK.md"
        work.rename(work.with_name("PRD.md"))
        result = feature.gate_check(self.name, agent="qa", root=self.root)
        self.assertEqual(result["track"], "light")
        self.assertIn("SECURITY-AUDIT.md", result["agent_gate"]["missing"])

    def test_prd_symlink_is_rejected_before_reading(self) -> None:
        directory = self.root / "docs" / self.name
        directory.mkdir(parents=True)
        (directory / "PRD.md").symlink_to(ROOT / "templates/PRD.md")
        with patch.object(feature.frontmatter, "read", side_effect=AssertionError("must not read")):
            self.assertFalse(feature.gate_check(self.name, root=self.root)["passed"])

    def test_invalid_configuration_is_unverified(self) -> None:
        self._work("low")
        with patch.object(feature, "risk_rules", side_effect=ValueError("invalid rules")):
            result = feature.gate_check(self.name, root=self.root)
        self.assertEqual(result["risk"]["status"], "unverified")
        self.assertFalse(result["passed"])

    def test_project_nested_in_another_repo_is_not_silently_rebound(self) -> None:
        self._work("low")
        with patch.object(feature, "_git_output", return_value=str(self.root.parent)):
            result = feature.gate_check(self.name, root=self.root)
        self.assertEqual(result["risk"]["status"], "unverified")
        self.assertFalse(result["passed"])

    def test_cli_and_mcp_forward_base(self) -> None:
        from agent_platform_mcp import cli, server
        from agent_platform_mcp.tools import handoff

        with patch.object(feature, "gate_check", return_value={"passed": True}) as gate, patch.object(cli, "_print_result"):
            self.assertEqual(cli.main(["gate-check", self.name, "--risk-base", "main"]), 0)
            self.assertEqual(gate.call_args.kwargs["risk_base"], "main")
            server.feature_gate_check(self.name, risk_base="main")
            self.assertEqual(gate.call_args.kwargs["risk_base"], "main")
        with patch.object(handoff, "validate", return_value={"passed": True}) as transfer, patch.object(cli, "_print_result"):
            self.assertEqual(cli.main(["handoff", "backend", "reviewer", self.name, "--risk-base", "main"]), 0)
            self.assertEqual(transfer.call_args.kwargs["risk_base"], "main")
            server.handoff_validate("backend", "reviewer", self.name, risk_base="main")
            self.assertEqual(transfer.call_args.kwargs["risk_base"], "main")

    def test_handoff_blocks_unverified_risk_even_without_test_execution(self) -> None:
        from agent_platform_mcp.tools import handoff

        self._work("low")
        result = handoff.validate("planner", "backend", self.name, root=self.root, verify=False)
        self.assertFalse(result["passed"])
        self.assertEqual(result["gate_check"]["risk"]["status"], "unverified")


class RiskRulesConfigTest(unittest.TestCase):
    def test_risk_rules_reads_paths_and_defaults_to_empty(self) -> None:
        from agent_platform_mcp import config

        with patch("agent_platform_mcp.config.agent_config", return_value={"risk_rules": {"paths": ["a/**"]}}):
            self.assertEqual(config.risk_rules(), {"paths": ["a/**"]})
        with patch("agent_platform_mcp.config.agent_config", return_value={}):
            self.assertEqual(config.risk_rules(), {"paths": []})

    def test_invalid_rules_are_not_silently_discarded(self) -> None:
        from agent_platform_mcp import config

        for rules in ({"paths": "auth/**"}, {"paths": ["a/**", 3]}, {"paths": [""]}, []):
            with self.subTest(rules=rules), patch("agent_platform_mcp.config.agent_config", return_value={"risk_rules": rules}):
                with self.assertRaises(ValueError):
                    config.risk_rules()

    def test_shipped_config_declares_auth_migration_patterns(self) -> None:
        from agent_platform_mcp import config

        paths = config.risk_rules()["paths"]
        self.assertTrue(any("auth" in p for p in paths), paths)
        self.assertTrue(any("migration" in p for p in paths), paths)


if __name__ == "__main__":
    unittest.main()
