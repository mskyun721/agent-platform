# Public Arithmetic API

Add divide(a, b) to calc/__init__.py. It returns a / b, including signed and zero
numerators, and raises ZeroDivisionError for a zero denominator. Keep add/subtract
behavior. Add test_divide and test_divide_by_zero as plain no-argument test
functions with assertions in tests/test_calc.py. Import divide at module scope.
Use try/except for the exception test. Run pytest.

The external evaluator also invokes divide through a real local HTTP adapter to
verify success, invalid input and zero-denominator responses. No server deployment
or external network access is part of this task.
