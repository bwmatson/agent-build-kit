# Proposal

## Why

`tests/test_marked_time_limit.py` and `tests/test_e2e_time_limit.py` test the time-limit plugin by writing a module's source from a string constant into a temporary folder and running pytest on it. In the unit branch of `fix-flaky-tests-test-marked-time-limit-py-test-a-marked-test-8237727a` (not yet merged) the file holds a fixture's source in `RECORDER` (`tests/test_marked_time_limit.py:17-38`), two more strings built on it with `.format(fire=...)` (`:40-57`, `:59-71`), and every test passes one to `run_child`. Code in a string is not linted, type-checked or navigable: a typo in it surfaces only as a failing child run, a `{` in it must be doubled, and a debugger or an editor's "go to definition" does not enter it. The pattern is not confined to these files: about 25 test modules and helpers write a child's source from a string (design.md lists them).

## What Changes

- **Real files.** The child code of the time-limit tests lives in `tests/child_modules/<scenario>/`, one folder per scenario family, holding the child's `conftest.py`, its modules and its `pytest.ini`. Ruff, pyrefly and the pre-commit hooks already cover `tests/`, so they check these files with no new setting.
- **Run with pytest's own `pytester`.** One helper, `tests/child_pytest.py` `run_scenario`, copies a scenario folder into the test's `pytester` directory (`Pytester.copy_example`, which reads the `pytester_example_dir` ini key, set to `tests/child_modules`), runs the named module in a subprocess with `-p tests.time_limit` and returns the exit code and the output. The values a string used to take through `.format()` go in through the command line and one environment variable.
- **Not collected by the repo's own runs.** `tests/conftest.py` ignores `child_modules/*`, and no file in the folder is named `test_*.py`.
- **Determinism is kept and checked.** The marked-limit scenarios still read the interval the hook armed from a recording timer and fire the first timer at once to block; a test over their files fails if one imports `time` or calls a sleep or a clock.
- **A guard for new string-built children.** A meta-test over the tracked test sources fails a module that both holds a string defining a test, fixture or hook and passes a source to a pytest run; the existing modules (listed in design.md) are in an allow-list that may only shrink.
- **Docs and changelog:** the convention in `AGENTS.md`, the test-hazards section of `docs/architecture.md`, one changelog bullet.

## Impact

- Capabilities: `test-determinism` (modified: child pytest code is held as files), `repo-wide-guards` (new requirement: the string-built child guard).
- agent-build-kit: `tests/child_pytest.py`, `tests/child_modules/`, `tests/conftest.py`, `tests/test_marked_time_limit.py`, `tests/test_e2e_time_limit.py`, `tests/child_sources.py`, `tests/test_child_pytest_sources_are_real_files.py`, `pyproject.toml` (`pytester_example_dir`), `AGENTS.md`, `docs/architecture.md`, `CHANGELOG.md`.
- Not in this change: the other string-built modules (allow-listed), `tests/test_time_limit.py` (its own `run_pytest`), the plugin itself, the pipeline.
- Depends on `fix-flaky-tests-test-marked-time-limit-py-test-a-marked-test-8237727a` group 1 being merged: that unit rewrites the file this change rewrites.
