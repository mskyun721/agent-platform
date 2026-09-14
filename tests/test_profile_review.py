import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_platform_mcp import config
from agent_platform_mcp.tools import profile_review, projects, verification


class ProfileReviewTest(unittest.TestCase):
    def test_review_metadata_does_not_change_profile_semantics_and_code_change_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            path = root / ".agent-config.json"
            profile = {"argv": ["python", "-m", "pytest"], "scope": {"acs": ["AC-1"]}}
            path.write_text(json.dumps({"verify_profiles": {"unit": profile}, "unrelated": {"keep": True}}))
            original_hash = verification.profile_hash(profile)
            with patch.object(config, "ROOT", root), patch.object(verification, "ROOT", root), \
                 patch.object(projects, "REGISTRY_FILE", root / ".agent-projects.json"), \
                 patch.object(verification, "verifier_hash", return_value="a" * 64), \
                 patch.object(profile_review.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "b" * 40, "")):
                result = profile_review.approve("unit", "human-reviewer")
                self.assertEqual(result["reviewed_hash"], original_hash)
                updated = json.loads(path.read_text())
                self.assertEqual(updated["unrelated"], {"keep": True})
                approved = updated["verify_profiles"]["unit"]
                self.assertEqual(verification.profile_hash(approved), original_hash)
                with patch.object(verification.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")):
                    status, report = verification._policy(approved, root)
                    self.assertEqual(status, "unchanged")
                    self.assertEqual(report["approval_provenance"], "complete")
                    with patch.object(verification, "verifier_hash", return_value="c" * 64):
                        self.assertEqual(verification._policy(approved, root)[0], "changed")
                    approved["argv"].append("-q")
                    self.assertEqual(verification._policy(approved, root)[0], "changed")

    def test_atomic_failure_preserves_operator_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            path = root / ".agent-config.json"
            original = json.dumps({"verify_profiles": {"unit": {"argv": ["true"]}}})
            path.write_text(original)
            with patch.object(config, "ROOT", root), patch.object(projects, "REGISTRY_FILE", root / ".agent-projects.json"), \
                 patch.object(verification, "verifier_hash", return_value="a" * 64), \
                 patch.object(profile_review.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "b" * 40, "")), \
                 patch.object(profile_review.os, "replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    profile_review.approve("unit", "human")
            self.assertEqual(path.read_text(), original)
