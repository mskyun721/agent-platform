from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
import run_task


class EvalRunnerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "workspace"
        self.patch = patch.object(run_task, "RESULTS", self.root / "results")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def setup_task(self, task):
        result = run_task.setup(task, self.workspace, ai="codex", model="test", cli_version="test")
        return result["run_id"]

    def test_metadata_is_external_and_contains_baseline_identity(self):
        run_id = self.setup_task("seeded-bug")
        state = json.loads((run_task.RESULTS / f"{run_id}.json").read_text())
        self.assertIn("task_hash", state)
        self.assertIn("platform_revision", state)
        self.assertFalse((self.workspace / ".eval-start.json").exists())

    def test_seeded_bug_fails_then_fix_passes(self):
        run_id = self.setup_task("seeded-bug")
        self.assertFalse(run_task.check(run_id)["passed"])
        impl = self.workspace / "calc/__init__.py"
        impl.write_text(impl.read_text().replace("return b - a", "return a - b"))
        self.assertTrue(run_task.check(run_id)["passed"])

    def test_deleted_test_is_not_a_test_repair(self):
        run_id = self.setup_task("broken-test")
        test = self.workspace / "tests/test_calc.py"
        test.write_text("from calc import add\ndef test_add():\n    assert add(2, 3) == 5\n")
        self.assertFalse(run_task.check(run_id)["passed"])

    def test_vacuous_test_fails_and_repaired_test_passes(self):
        run_id = self.setup_task("broken-test")
        test = self.workspace / "tests/test_calc.py"
        original = test.read_text()
        test.write_text(original.replace("assert subtract(5, 3) == 3", "assert True"))
        self.assertFalse(run_task.check(run_id)["passed"])
        test.write_text(original.replace("assert subtract(5, 3) == 3", "assert subtract(5, 3) == 2"))
        self.assertTrue(run_task.check(run_id)["passed"])

    def test_workspace_hash_forgery_cannot_bypass_unchanged_rule(self):
        run_id = self.setup_task("seeded-bug")
        test = self.workspace / "tests/test_calc.py"
        test.write_text(test.read_text().replace("== 2", "== -2"))
        (self.workspace / ".eval-start.json").write_text(json.dumps({"tests/test_calc.py": run_task._hash(test)}))
        self.assertFalse(run_task.check(run_id)["passed"])

    def test_incorrect_multiply_with_weak_test_is_rejected(self):
        run_id = self.setup_task("small-feature")
        impl = self.workspace / "calc/__init__.py"
        impl.write_text(impl.read_text() + "\ndef multiply(a, b):\n    return 0\n")
        test = self.workspace / "tests/test_calc.py"
        test.write_text(test.read_text() + "\ndef test_multiply():\n    assert True\n")
        self.assertFalse(run_task.check(run_id)["passed"])

    def test_correct_multiply_and_meaningful_test_pass(self):
        run_id = self.setup_task("small-feature")
        impl = self.workspace / "calc/__init__.py"
        impl.write_text(impl.read_text() + "\ndef multiply(a, b):\n    return a * b\n")
        test = self.workspace / "tests/test_calc.py"
        test.write_text(test.read_text() + "\nfrom calc import multiply\ndef test_multiply():\n    assert multiply(2, 3) == 6\n")
        self.assertTrue(run_task.check(run_id, human_interventions=2)["passed"])

    def test_nonempty_workspace_and_unsafe_task_are_rejected(self):
        self.setup_task("seeded-bug")
        with self.assertRaises(FileExistsError):
            self.setup_task("seeded-bug")
        with self.assertRaises(ValueError):
            run_task.setup("../escape", self.workspace)

    def test_skip_is_not_success(self):
        result = run_task.record_skip("small-feature", "claude", "not run in implementation test")
        self.assertEqual(result["status"], "not_run")
        self.assertNotIn("passed", result)

    def test_symlink_cannot_supply_evaluated_code(self):
        run_id = self.setup_task("seeded-bug")
        impl = self.workspace / "calc/__init__.py"
        impl.unlink()
        impl.symlink_to(run_task.FIXTURE / "calc/__init__.py")
        self.assertFalse(run_task.check(run_id)["passed"])
