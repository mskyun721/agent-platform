from __future__ import annotations

import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server" / "src"))

GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


class GitInitAndCommitTest(unittest.TestCase):
    def test_returns_actual_short_commit_hash(self) -> None:
        from agent_platform_mcp.tools import project

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "proj"
            dest.mkdir()
            (dest / "README.md").write_text("hello\n", encoding="utf-8")

            with patch.dict("os.environ", GIT_ENV):
                result = project._git_init_and_commit(dest, "proj")

            expected = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(dest),
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

            self.assertTrue(result["git_init"])
            self.assertEqual(result["commit_hash"], expected)


class JavaProjectArchiveSafetyTest(unittest.TestCase):
    def _malicious_tgz(self, path: Path) -> None:
        """Create a tgz containing a member that escapes the extraction dir."""
        with tarfile.open(path, "w:gz") as tar:
            data = b"evil"
            info = tarfile.TarInfo(name="../evil.txt")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    def test_rejects_path_traversal_members(self) -> None:
        from agent_platform_mcp.tools import project

        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp) / "workspace"
            target_dir.mkdir()
            evil_tgz = Path(tmp) / "payload.tgz"
            self._malicious_tgz(evil_tgz)

            def fake_retrieve(url: str, filename: Path) -> None:
                Path(filename).write_bytes(evil_tgz.read_bytes())

            with patch("urllib.request.urlretrieve", side_effect=fake_retrieve):
                with self.assertRaises(tarfile.FilterError):
                    project._generate_java_project(
                        target_dir,
                        "my-service",
                        "com.example.myservice",
                        java_version=21,
                        spring_boot_version=None,
                        dependencies=None,
                    )

            self.assertFalse((target_dir / "evil.txt").exists())


if __name__ == "__main__":
    unittest.main()
