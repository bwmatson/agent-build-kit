# test-child-pytest-sources-are-real-files

The tests that drive a pytest plugin in a child pytest keep the child's code in real files under `tests/child_modules/<scenario>/`, not in Python strings, so ruff, pyrefly and the editor read it; the child is started with pytest's own `pytester` (`copy_example`), and a guard fails a new test module that builds a child's source as a string. The time-limit tests (`test_marked_time_limit.py`, `test_e2e_time_limit.py`) move first; the other string-built modules are listed in the guard's allow-list to migrate later.
