"""Evaluator-owned behavior checks, executed outside the edited workspace."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from types import ModuleType
import pytest

STAGES = {"load", "behavior", "test_contract", "original_tests", "mutation_add", "mutation_subtract",
          "mutation_multiply", "mutation_divide", "mutation_divide_by_zero", "zero_denominator", "http", "skill"}
stage = "load"


def rejects_mutant(namespace, module, symbol, test, mutant):
    original = getattr(module, symbol)
    bindings = {name: value for name, value in namespace.items() if value is original}
    setattr(module, symbol, mutant)
    namespace.update({name: mutant for name in bindings})
    try:
        try:
            namespace[test]()
        except (AssertionError, pytest.fail.Exception):
            return
        raise AssertionError("required test did not reject mutant")
    finally:
        setattr(module, symbol, original)
        namespace.update(bindings)


def judge(workspace: Path, expect: dict) -> None:
    global stage
    stage = "load"
    module = ModuleType("calc")
    source = workspace / "calc/__init__.py"
    exec(compile(source.read_text(), str(source), "exec"), module.__dict__)
    stage = "behavior"
    for a, b in [(2, 3), (0, 8), (-4, 3), (11, -2), (-3, -7)]:
        assert module.add(a, b) == a + b, "add behavior"
        assert module.subtract(a, b) == a - b, "subtract behavior"
        if expect["behavior"] == "multiply":
            assert module.multiply(a, b) == a * b, "multiply behavior"
        if expect["behavior"] == "divide":
            assert module.divide(a, b) == a / b, "divide behavior"

    stage = "test_contract"
    tree = ast.parse((workspace / "tests/test_calc.py").read_text())
    tests = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for name in expect["required_tests"]:
        assert name in tests, f"missing required test {name}"

    # A restored test must reject the original defect, not just exist and pass.
    namespace = {"__name__": "eval_test", "__file__": str(workspace / "tests/test_calc.py")}
    stage = "original_tests"
    sys.modules["calc"] = module
    exec(compile(tree, str(workspace / "tests/test_calc.py"), "exec"), namespace)
    for name in expect["required_tests"]:
        namespace[name]()
    for symbol, test in [("subtract", "test_subtract"), ("add", "test_add")]:
        stage = "mutation_" + symbol
        rejects_mutant(namespace, module, symbol, test, lambda a, b: 999999)
    if expect["behavior"] == "multiply":
        stage = "mutation_multiply"
        rejects_mutant(namespace, module, "multiply", "test_multiply", lambda a, b: 0)
    if expect["behavior"] == "divide":
        stage = "zero_denominator"
        try:
            module.divide(1, 0)
        except ZeroDivisionError:
            pass
        else:
            raise AssertionError("zero denominator must fail")
        for name in ("test_divide", "test_divide_by_zero"):
            stage = "mutation_" + name.removeprefix("test_")
            rejects_mutant(namespace, module, "divide", name, lambda a, b: 999999)
        stage = "http"
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from http_judge import check
        check(module)
    if expect["behavior"] == "skill-remove":
        stage = "skill"
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from skill_judge import check
        check(workspace)


if __name__ == "__main__":
    try:
        judge(Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()))
    except BaseException:
        print(json.dumps({"evaluator_stage": stage if stage in STAGES else "load"}))
        raise SystemExit(1)
