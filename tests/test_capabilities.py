import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_capabilities as capabilities


class CapabilityTest(unittest.TestCase):
    def test_missing_binary_is_unavailable(self):
        with patch.object(capabilities.shutil, "which", return_value=None), patch.object(capabilities.subprocess, "run") as run:
            self.assertEqual(capabilities.probe("codex")["status"], "unavailable")
        run.assert_not_called()

    def test_version_and_flags_are_only_reported_from_help(self):
        outputs = [subprocess.CompletedProcess([], 0, "codex-cli 0.154.0", ""),
                   subprocess.CompletedProcess([], 0, "--sandbox <MODE>\n--json\n", "")]
        with patch.object(capabilities.shutil, "which", return_value="codex"), patch.object(capabilities.subprocess, "run", side_effect=outputs):
            result = capabilities.probe("codex")
        self.assertEqual(result["version"], "0.154.0")
        self.assertEqual(result["flags"]["--sandbox"], "supported")
        self.assertEqual(result["flags"]["--output-schema"], "unverified")

    def test_timeout_does_not_stop_other_backend_probe(self):
        with patch.object(capabilities.shutil, "which", side_effect=["claude", None]), \
             patch.object(capabilities.subprocess, "run", side_effect=subprocess.TimeoutExpired("claude", 10)):
            result = capabilities.snapshot()
        self.assertEqual([entry["status"] for entry in result["backends"]], ["error", "unavailable"])

    def test_probe_does_not_accept_arbitrary_commands(self):
        with self.assertRaises(ValueError):
            capabilities.probe("sh")
