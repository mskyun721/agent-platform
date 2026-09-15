# Public Arithmetic API

Add divide(a, b) to calc/__init__.py. It returns a / b, including signed and zero
numerators, and raises ZeroDivisionError for a zero denominator. Keep add/subtract
behavior. Add test_divide and test_divide_by_zero as plain no-argument test
functions in tests/test_calc.py. Tests must reject incorrect results and a missing
zero-denominator exception. Native assert, explicit AssertionError and pytest.raises
are supported; imports may be module-qualified or aliased. Run pytest.

The external evaluator also invokes divide through a real local HTTP adapter to
verify success, invalid input and zero-denominator responses. No server deployment
or external network access is part of this task.
