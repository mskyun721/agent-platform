import sys
import unittest
import subprocess
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pr_logic_size as size


class LogicSizeTest(unittest.TestCase):
    def test_real_git_commits_exclude_tests_and_pending_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
            git("init")
            git("config", "user.email", "fixture@example.invalid")
            git("config", "user.name", "Fixture")
            (root / "app.py").write_text("value = 1\n")
            git("add", "app.py")
            git("commit", "-m", "base")
            base = git("rev-parse", "HEAD")
            (root / "app.py").write_text("import os\n# note\nvalue = 2\n")
            (root / "test_app.py").write_text("assert True\n")
            git("add", "app.py", "test_app.py")
            git("commit", "-m", "feature")
            (root / "app.py").write_text("uncommitted = 3\n")
            result = size.report(root, base)
            self.assertEqual(result["logic_lines"], 2)
            self.assertTrue(result["within_limit"])
            self.assertFalse(result["pending_changes_included"])
            self.assertEqual(result["excluded"], [{"path": "test_app.py", "reason": "test"}])

    def test_comments_imports_docstrings_and_mixed_line_logic(self):
        source = '"""module docs\nmore docs"""\nimport os\nfrom pathlib import (\n    Path,\n)\n# comment\nvalue = 1 # inline\nimport sys; value += 1\n'
        lines, mode = size.logic_lines(source, ".py")
        self.assertEqual(lines, {8, 9})
        self.assertEqual(mode, "exact")

    def test_added_plus_deleted_and_500_boundary(self):
        old = "\n".join(f"value_{i} = 1" for i in range(250))
        new = "\n".join(f"value_{i} = 2" for i in range(250))
        self.assertEqual(size.compare("app.py", old, new)["logic_lines"], 500)
        self.assertEqual(size.compare("app.py", old, new + "\nextra = 1")["logic_lines"], 501)

    def test_unclassified_languages_are_conservative_not_falsely_exact(self):
        result = size.compare("Service.kt", "", "import x\n// comment\nfun run() = 1\n")
        self.assertEqual(result["logic_lines"], 3)
        self.assertIn("conservative", result["classification"])
        self.assertIsNotNone(size.excluded("src/test/kotlin/ServiceTest.kt"))
        self.assertIsNotNone(size.excluded("config.yaml"))
        self.assertIsNotNone(size.excluded(".env"))
