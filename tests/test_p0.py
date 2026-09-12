"""Regression coverage for P0 contracts and review findings."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from test_feature_tools import ActiveProjectTestCase
from agent_platform_mcp import cli, config, server
from agent_platform_mcp.tools import feature, handoff, verification


class ExplicitProjectTest(unittest.TestCase):
    def test_self_target_without_environment_does_not_allow_descendants(self):
        with patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": ""}):
            self.assertEqual(config.resolve_project_dir(config.ROOT), config.ROOT.resolve())
            with self.assertRaises(RuntimeError):
                config.resolve_project_dir(config.ROOT / "mcp-server")

    def test_explicit_root_validates_directory_and_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.dict(os.environ, {"AGENT_PLATFORM_ALLOWED_PROJECT_ROOTS": str(root / "allowed")}):
                with self.assertRaises(RuntimeError):
                    config.resolve_project_dir(root)
                with self.assertRaises(FileNotFoundError):
                    config.resolve_project_dir(root / "missing")


class P0GateTest(ActiveProjectTestCase):
    def test_empty_fails(self):
        (self.resolved_target / "docs/features/empty").mkdir(parents=True)
        result = feature.gate_check("empty")
        self.assertFalse(result["passed"])
        self.assertTrue(result["empty"])

    def test_canonical_names_and_legacy_warning(self):
        with self.assertRaises(ValueError):
            feature.canonical_feature("pay\n")
        result = feature.scaffold("features/pay")
        self.assertEqual(result["feature"], "pay")
        self.assertTrue(feature.gate_check("features/pay")["passed"])
        for name, valid in [("refactor/pay", True), ("refactor/db/pay", False)]:
            path = self.write_artifact(name, "PRD.md")
            path.write_text(path.read_text().replace(f"feature: {name}", "feature: pay"))
            result = feature.gate_check(name)
            self.assertEqual(result["passed"], valid)
            if valid:
                self.assertIn("legacy bare", result["files"][0]["warnings"][0])

    def test_links_resolve_by_prefix_and_reject_escape(self):
        self.write_artifact("fix/pay", "PRD.md")
        path = self.write_artifact("fix/pay", "REVIEW.md")
        original = path.read_text()
        for rel, valid in [("PRD.md", True), ("docs/fix/pay/PRD.md", True),
                           ("https://example.com/spec", True), ("NOPE.md", False),
                           ("/etc/hosts", False), ("../../../README.md", False)]:
            with self.subTest(rel=rel):
                path.write_text(original.replace("---\n\n", f"links:\n  prd: {rel}\n---\n\n"))
                self.assertEqual(feature.gate_check("fix/pay")["passed"], valid)

    def test_artifact_symlink_is_never_read(self):
        path = self.write_artifact("pay", "PRD.md")
        path.unlink()
        path.symlink_to(self.resolved_target / "outside.md")
        self.assertFalse(feature.gate_check("pay")["passed"])
        with self.assertRaises(ValueError):
            feature.list_artifacts("pay")

    def test_docs_symlink_is_not_followed(self):
        other = self.resolved_target / "other"
        other.mkdir()
        (self.resolved_target / "docs").symlink_to(other, target_is_directory=True)
        with self.assertRaises(ValueError):
            feature.scaffold("pay")

    def test_two_roots_concurrently_do_not_mutate_environment(self):
        other = self.resolved_target / "other"
        other.mkdir()
        feature.scaffold("pay", root=other)
        self.write_artifact("pay", "PRD.md", status="approved")
        (other / "docs/features/pay/PRD.md").write_text("# invalid")
        before = dict(os.environ)
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda root: feature.gate_check("pay", root=root), [self.resolved_target, other]))
        self.assertEqual([r["passed"] for r in results], [True, False])
        self.assertEqual(before, dict(os.environ))

    def _verify(self, profile=None, **kwargs):
        self.write_artifact("fix/pay", "PRD.md")
        cfg = {"verify_profiles": {"test": profile}} if profile is not None else {}
        with patch.object(feature, "agent_config", return_value=cfg):
            return feature.gate_check("fix/pay", verify=True,
                                      verify_profile="test" if profile is not None else None, **kwargs)

    def test_verification_missing_and_exit_codes(self):
        self.assertEqual(self._verify()["verification_status"], "not_run")
        for code in (0, 1):
            result = self._verify({"argv": [sys.executable, "-c", f"raise SystemExit({code})"]})
            self.assertEqual(result["passed"], code == 0)
            self.assertEqual(result["verify_exit_code"], code)
            self.assertIsInstance(result["verify_command"], str)

    def test_invalid_profiles_and_cwd_cannot_execute(self):
        with patch.object(verification.subprocess, "run") as run:
            for profile in [
                {"argv": "true"}, {"argv": []}, {"command": "true"},
                {"argv": ["true"], "command": "true"},
                {"argv": ["true"], "cwd": "/tmp"},
                {"argv": ["true"], "cwd": "../"},
                {"argv": ["true"], "timeout_sec": 0},
                {"argv": ["true"], "timeout_sec": "900"},
            ]:
                with self.subTest(profile=profile):
                    result = self._verify(profile)
                    self.assertEqual(result["verification_status"], "error")
                    self.assertFalse(result["passed"])
            # The gate may read git state (risk cross-check); the profile's
            # command itself must never have been executed.
            executed = [c.args[0] for c in run.call_args_list if c.args and c.args[0][0] != "git"]
            self.assertEqual(executed, [])

    def test_symlink_cwd_outside_root_is_rejected(self):
        (self.resolved_target / "escape").symlink_to(self.resolved_target.parent, target_is_directory=True)
        result = self._verify({"argv": ["true"], "cwd": "escape"})
        self.assertEqual(result["verification_status"], "error")

    def test_timeout_and_permission_errors_are_reported(self):
        result = self._verify({"argv": [sys.executable, "-c", "import time; time.sleep(3)"], "timeout_sec": 0.05})
        self.assertEqual(result["verification_status"], "error")
        executable = self.resolved_target / "not-executable"
        executable.write_text("not executable")
        result = self._verify({"argv": [str(executable)]})
        self.assertEqual(result["verification_status"], "error")

    def test_policy_changes_do_not_block_test_execution(self):
        profile = {"argv": [sys.executable, "-c", "pass"], "reviewed_hash": "old"}
        result = self._verify(profile)
        self.assertEqual(result["policy_status"], "changed")
        self.assertTrue(result["passed"])
        cfg = {"verify_profiles": {"p": profile}, "skills": {"enabled": []}, "pricing": {"rate": 1}}
        first = verification.profile_hash(cfg["verify_profiles"]["p"])
        cfg["skills"]["enabled"].append("example")
        cfg["pricing"]["rate"] = 2
        self.assertEqual(first, verification.profile_hash(cfg["verify_profiles"]["p"]))

    def test_build_marker_does_not_auto_execute(self):
        (self.resolved_target / "gradlew").write_text("invalid")
        self.write_artifact("fix/pay", "PRD.md")
        with patch.object(feature, "agent_config", return_value={"verify_profiles": {"gradle": {"argv": ["false"]}}}):
            result = feature.gate_check("fix/pay", verify=True)
        self.assertEqual(result["verification_status"], "not_run")
        self.assertEqual(result["verification"]["suggested_profiles"], ["gradle"])

    def test_rejected_decision_can_be_handed_back_for_each_role(self):
        for role, filename in [("reviewer", "REVIEW.md"), ("security", "SECURITY-AUDIT.md"), ("qa", "TEST-PLAN.md")]:
            self.write_artifact("fix/pay", filename, agent=role, status="rejected")
            result = handoff.validate(role, "backend", "fix/pay", purpose="rework")
            self.assertTrue(result["passed"], result)
            self.assertIsNone(result["verification_status"])

    def test_plan_review_does_not_require_implementation_outputs(self):
        self.write_artifact("pay", "PRD.md", status="draft")
        self.write_artifact("pay", "TASK.md", status="draft")
        result = handoff.validate("planner", "reviewer", "pay", purpose="plan_review")
        self.assertTrue(result["passed"], result)
        self.assertIsNone(result["verification_status"])

    def test_completion_requires_source_approval(self):
        self.write_artifact("fix/pay", "PRD.md")
        self.write_artifact("fix/pay", "REVIEW.md", agent="reviewer", status="draft")
        result = handoff.validate("reviewer", "backend", "fix/pay", purpose="implementation_complete")
        self.assertFalse(result["passed"])
        self.assertIn("not approved", result["source_output_errors"][0])

    def test_cli_and_mcp_propagate_explicit_root_and_profile(self):
        self.write_artifact("fix/pay", "PRD.md")
        with patch.object(feature, "agent_config", return_value={"verify_profiles": {"p": {"argv": [sys.executable, "-c", "pass"]}}}):
            output = StringIO()
            with redirect_stdout(output):
                code = cli.main(["gate-check", "fix/pay", "--root", str(self.resolved_target), "--verify", "--verify-profile", "p"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["verification_status"], "passed")
            result = server.feature_gate_check("fix/pay", root=str(self.resolved_target), verify=True, verify_profile="p")
            self.assertTrue(result["passed"])
        with redirect_stdout(StringIO()):
            self.assertEqual(cli.main(["gate-check", "fix/pay", "--verify", "--root", str(self.resolved_target)]), 1)

    def test_unchanged_review_policy_is_only_advisory(self):
        profile = {"argv": ["true"]}
        profile["reviewed_hash"] = verification.profile_hash(profile)
        with patch.object(verification, "VERIFIER_FILES", ()):
            status, report = verification._policy(profile, self.resolved_target)
        # Dirty working tree inspection may report changes; it must never
        # create artifact approval or claim an independent reviewer ran.
        self.assertIn(status, {"unchanged", "changed", "unreviewed"})
        self.assertIn("advisory", report["enforcement"])
