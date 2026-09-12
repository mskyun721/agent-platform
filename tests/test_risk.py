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
        self.assertTrue(result["passed"], result["files"])

    def test_no_rules_configured_means_no_hits(self) -> None:
        self._git("init", "-q")
        self._work("low")
        self._touch("src/main/kotlin/auth/Token.kt")
        with patch("agent_platform_mcp.tools.feature.risk_rules", return_value={"paths": []}):
            result = feature.gate_check(self.name, root=self.root)

        self.assertEqual(result["risk"]["status"], "ok")


class RiskRulesConfigTest(unittest.TestCase):
    def test_risk_rules_reads_paths_and_defaults_to_empty(self) -> None:
        from agent_platform_mcp import config

        with patch("agent_platform_mcp.config.agent_config", return_value={"risk_rules": {"paths": ["a/**", 3]}}):
            self.assertEqual(config.risk_rules(), {"paths": ["a/**"]})
        with patch("agent_platform_mcp.config.agent_config", return_value={}):
            self.assertEqual(config.risk_rules(), {"paths": []})

    def test_shipped_config_declares_auth_migration_patterns(self) -> None:
        from agent_platform_mcp import config

        paths = config.risk_rules()["paths"]
        self.assertTrue(any("auth" in p for p in paths), paths)
        self.assertTrue(any("migration" in p for p in paths), paths)


if __name__ == "__main__":
    unittest.main()
