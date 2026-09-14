import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_platform_mcp.tools.fingerprint import code_fingerprint


class FingerprintTest(unittest.TestCase):
    def test_code_changes_but_document_and_secret_contents_are_not_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = root / "app.py"
            source.write_text("value = 1\n")
            before = code_fingerprint(root)
            (root / "docs").mkdir()
            (root / "docs/WORK.md").write_text("documentation")
            (root / ".env").touch()
            read = Path.read_bytes
            def guard(path):
                if path.name == ".env" or "docs" in path.parts:
                    raise AssertionError("excluded content read")
                return read(path)
            with patch.object(Path, "read_bytes", guard):
                self.assertEqual(code_fingerprint(root)["fingerprint"], before["fingerprint"])
            source.write_text("value = 2\n")
            self.assertNotEqual(code_fingerprint(root)["fingerprint"], before["fingerprint"])

    def test_real_git_tracked_untracked_delete_and_mode_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            source = root / "app.py"
            source.write_text("value = 1\n")
            subprocess.run(["git", "add", "app.py"], cwd=root, check=True)
            before = code_fingerprint(root)
            (root / "new.py").write_text("new = 1\n")
            self.assertNotEqual(code_fingerprint(root)["untracked"], before["untracked"])
            source.chmod(0o755)
            self.assertNotEqual(code_fingerprint(root)["tracked_diff"], before["tracked_diff"])
            source.unlink()
            self.assertEqual(code_fingerprint(root)["files"]["app.py"], {"deleted": True})

    def test_symlink_fails_instead_of_reading_external_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "app.py").symlink_to("/etc/hosts")
            with self.assertRaises(ValueError):
                code_fingerprint(root)
