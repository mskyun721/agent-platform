import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
import auto
import run_task
import summarize


class EvaluationAutomationTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        mock = patch.object(run_task, "RESULTS", self.root / "results")
        mock.start()
        self.addCleanup(mock.stop)

    def test_auto_isolated_fake_cli_and_budget_outcome(self):
        seen = []
        def solve(argv, workspace, timeout):
            self.assertFalse(workspace.is_relative_to(run_task.ROOT))
            self.assertIn("--sandbox", argv)
            self.assertGreater(timeout, 0)
            seen.append(workspace)
            (workspace / "calc/__init__.py").write_text((run_task.FIXTURE / "calc/__init__.py").read_text())
            return {"exit_code": 0, "reason": None, "stdout": "", "duration_sec": 0.1}
        with patch.object(auto, "execute", side_effect=solve):
            result = auto.run("seeded-bug", "codex", 1, 1)
        self.assertTrue(result["passed"])
        self.assertTrue(result["sample_insufficient"])
        self.assertFalse(seen[0].exists())
        with patch.object(auto, "execute", return_value={"exit_code": None, "reason": "budget", "stdout": "", "duration_sec": 1}):
            result = auto.run("seeded-bug", "codex", 1, 1)
        record = json.loads(run_task._state_file(result["runs"][0]["run_id"]).read_text())
        self.assertEqual(record["outcome"], "interrupted")
        self.assertFalse(record["passed"])

    def test_summary_separates_task_hash_and_detects_regression(self):
        base = {"task": "seeded-bug", "ai": "codex", "instruction_mode": "platform", "task_hash": "old",
                "status": "checked", "checked_at": "2026-09-14T00:00:00Z", "passed": True}
        failed = {**base, "checked_at": "2026-09-15T00:00:00Z", "passed": False, "failure_reason": "evaluator"}
        groups = summarize.summarize([base, failed, {**base, "task_hash": "new"}])
        self.assertEqual(len(groups), 2)
        self.assertTrue(all(row["sample_insufficient"] for row in groups))
        self.assertEqual(summarize.regress([base, failed], {"cases": [base]}), ["seeded-bug:codex:platform"])

    def test_interruption_does_not_launch_remaining_repeats(self):
        with patch.object(auto, "execute", return_value={"exit_code": None, "reason": "interrupted", "stdout": "", "duration_sec": 1}) as execute:
            result = auto.run("seeded-bug", "codex", 3, 1)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(result["completed"], 1)
        self.assertFalse(result["passed"])

    def test_real_skill_removal_judge_rejects_forged_result(self):
        workspace = self.root / "skill-fixture"
        state = run_task.setup("skill-remove", workspace)
        script = workspace / "exercise_skill.py"
        script.write_text("def exercise(enable, disable, remove):\n    return {'blocked_while_enabled': True, 'removed': True}\n")
        self.assertFalse(run_task.check(state["run_id"])["passed"])
        script.write_text("def exercise(enable, disable, remove):\n    blocked = False\n    try:\n        remove()\n    except RuntimeError:\n        blocked = True\n    disable()\n    result = remove()\n    return {'blocked_while_enabled': blocked, 'removed': result['removed']}\n")
        self.assertTrue(run_task.check(state["run_id"])["passed"])

    def test_real_http_judge_success_and_error_cases(self):
        workspace = self.root / "api-fixture"
        state = run_task.setup("api-add", workspace)
        source = workspace / "calc/__init__.py"
        source.write_text(source.read_text() + "\n\ndef divide(a, b):\n    return a / b\n")
        tests = workspace / "tests/test_calc.py"
        tests.write_text(tests.read_text() + "\nfrom calc import divide\n\ndef test_divide():\n    assert divide(6, 2) == 3\n\ndef test_divide_by_zero():\n    failed = False\n    try:\n        divide(1, 0)\n    except ZeroDivisionError:\n        failed = True\n    assert failed\n")
        result = run_task.check(state["run_id"])
        self.assertTrue(result["passed"], result)

    def test_module_qualified_and_aliased_calls_are_mutated(self):
        workspace = self.root / "qualified-api"
        state = run_task.setup("api-add", workspace)
        source = workspace / "calc/__init__.py"
        source.write_text(source.read_text() + "\ndef divide(a,b):\n    return a/b\n")
        tests = workspace / "tests/test_calc.py"
        tests.write_text("import calc\nfrom calc import divide as quotient\n"
                         "def test_add():\n    assert calc.add(2,3) == 5\n"
                         "def test_subtract():\n    assert calc.subtract(5,3) == 2\n"
                         "def test_divide():\n    assert quotient(8,2) == 4\n"
                         "def test_divide_by_zero():\n    caught = False\n    try:\n        calc.divide(1,0)\n    except ZeroDivisionError:\n        caught = True\n    assert caught\n")
        self.assertTrue(run_task.check(state["run_id"])["passed"])
        tests.write_text(tests.read_text().replace("assert quotient(8,2) == 4", "assert True"))
        result = run_task.check(state["run_id"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["evaluator_stage"], "mutation_divide")

    def test_valid_exception_tests_need_not_contain_ast_assert(self):
        workspace = self.root / "exception-api"
        state = run_task.setup("api-add", workspace)
        source = workspace / "calc/__init__.py"
        source.write_text(source.read_text() + "\ndef divide(a,b):\n    return a/b\n")
        path = workspace / "tests/test_calc.py"
        original = path.read_text()
        for exception_test in (
            "    try:\n        divide(1,0)\n    except ZeroDivisionError:\n        return\n    raise AssertionError('must raise')\n",
            "    with pytest.raises(ZeroDivisionError):\n        divide(1,0)\n",
        ):
            with self.subTest(style=exception_test.splitlines()[0]):
                path.write_text(original + "\nimport pytest\nfrom calc import divide\n"
                                "def test_divide():\n    assert divide(8,2) == 4\n"
                                "def test_divide_by_zero():\n" + exception_test)
                self.assertTrue(run_task.check(state["run_id"])["passed"])
        path.write_text(path.read_text().replace(exception_test, "    pass\n"))
        failed = run_task.check(state["run_id"])
        self.assertFalse(failed["passed"])
        self.assertEqual(failed["evaluator_stage"], "mutation_divide_by_zero")
