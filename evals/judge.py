"""Evaluator-owned behavior checks, executed outside the edited workspace."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from types import ModuleType


def judge(workspace: Path, expect: dict) -> None:
    module = ModuleType("calc")
    source = workspace / "calc/__init__.py"
    exec(compile(source.read_text(), str(source), "exec"), module.__dict__)
    for a, b in [(2, 3), (0, 8), (-4, 3), (11, -2), (-3, -7)]:
        assert module.add(a, b) == a + b, "add behavior"
        assert module.subtract(a, b) == a - b, "subtract behavior"
        if expect["behavior"] == "multiply":
            assert module.multiply(a, b) == a * b, "multiply behavior"
        if expect["behavior"] == "divide":
            assert module.divide(a, b) == a / b, "divide behavior"

    tree = ast.parse((workspace / "tests/test_calc.py").read_text())
    tests = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for name in expect["required_tests"]:
        assert name in tests, f"missing required test {name}"
        assert any(isinstance(node, ast.Assert) for node in ast.walk(tests[name])), f"no assertion in {name}"

    # A restored test must reject the original defect, not just exist and pass.
    namespace = {"__name__": "eval_test", "__file__": str(workspace / "tests/test_calc.py")}
    sys.modules["calc"] = module
    exec(compile(tree, str(workspace / "tests/test_calc.py"), "exec"), namespace)
    for name in expect["required_tests"]:
        namespace[name]()
    for symbol, test in [("subtract", "test_subtract"), ("add", "test_add")]:
        original = namespace.get(symbol)
        namespace[symbol] = lambda a, b: 999999
        try:
            try:
                namespace[test]()
            except AssertionError:
                pass
            else:
                raise AssertionError(f"{test} does not detect incorrect {symbol}")
        finally:
            namespace[symbol] = original
    if expect["behavior"] == "multiply":
        namespace["multiply"] = lambda a, b: 0
        try:
            namespace["test_multiply"]()
        except AssertionError:
            pass
        else:
            raise AssertionError("test_multiply does not detect incorrect multiply")
    if expect["behavior"] == "divide":
        try:
            module.divide(1, 0)
        except ZeroDivisionError:
            pass
        else:
            raise AssertionError("zero denominator must fail")
        namespace["divide"] = lambda a, b: 999999
        for name in ("test_divide", "test_divide_by_zero"):
            try:
                namespace[name]()
            except AssertionError:
                pass
            else:
                raise AssertionError(f"{name} does not detect incorrect divide")
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from http_judge import check
        check(module)
    if expect["behavior"] == "skill-remove":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from skill_judge import check
        check(workspace)


if __name__ == "__main__":
    judge(Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()))
