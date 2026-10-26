# Proposal

## Why

The parallel test run's warnings summary reports, four times, for `tests/pipeline/test_usage_one_authority.py::test_twenty_asks_from_several_processes_make_one_call`:

```
multiprocessing/popen_fork.py:66: DeprecationWarning: This process (pid=...) is multi-threaded, use of fork() may lead to deadlocks in the child.
```

The test starts its four askers with `multiprocessing.get_context("fork")`. Under the parallel runner the test's own process carries threads of the
runner, so the fork copies a process whose locks may be held by a thread that does not exist in the child. Python 3.12 warns; the repo's own interpreter
(3.14) changes the default start method away from `fork` for the same reason. The warning is also a latent hang: a child that inherits a held lock never
returns, and the test then waits out its 30-second queue timeout instead of failing for a reason. Nothing in the suite makes a warning of this kind fail,
so it was found by someone reading CI output.

## What Changes

- **The test's processes start with `spawn`.** The function the children run and everything it needs live in a helper module under `tests/`, and what
  the children used to inherit by forking is passed to them as arguments and rebuilt there (design: "What the children must rebuild").
- **The test is made to see the multi-threaded runner on any machine**: it keeps a thread alive while it starts the askers, so a regression to `fork`
  warns on a serial local run too, not only under the parallel runner.
- **The pytest options turn that warning into an error**, scoped by its message, so it fails the test that causes it. A test asserts the option is
  configured.
- **The `test-determinism` capability** gains a requirement that the suite starts no process by forking a multi-threaded process.

## Impact

- agent-build-kit: `tests/pipeline/test_usage_one_authority.py`, a new `tests/usage_asker.py`, a new `tests/test_warning_filters.py`, `pyproject.toml`
  (`[tool.pytest.ini_options]`). No framework source and no changelog entry (design: "No changelog").
- Spec: `test-determinism`.
