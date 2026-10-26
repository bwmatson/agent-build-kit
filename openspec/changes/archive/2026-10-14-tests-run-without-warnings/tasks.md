# Tasks

Acceptance: none — tier 1 only: a test, its helper and a pytest option; the tool's behaviour and everything a consumer sees are unchanged.

Priority: 4

## 1. [agent-build-kit] [tier1] The several-process test spawns its processes and warnings of that kind fail

Done when `test_twenty_asks_from_several_processes_make_one_call` starts its askers with `spawn` from a helper module, passes with the fork warning turned into an error while another thread is alive, and the pytest options make that warning fail the suite.

- [x] 1.1 Test: in `tests/test_warning_filters.py`, `[tool.pytest.ini_options]` has a `filterwarnings` entry that turns the multi-threaded-fork `DeprecationWarning` into an error and matches the text Python 3.12 gives it; a missing or loosened entry fails the test and names it.
- [x] 1.2 Test: in the same file, with that entry applied through `pytester`, a test that forks a process while a second thread is alive fails with the warning, and one that spawns passes.
- [x] 1.3 Test: `tests/pipeline/test_usage_one_authority.py::test_twenty_asks_from_several_processes_make_one_call` keeps a thread alive while it starts four processes with the `spawn` method and still asserts exactly one recorded call, no `None` answer, one `("live", 33)` answer among them and every session 14 or 33; it passes with the filter on, and fails if the context is `fork`.
- [x] 1.4 Add `tests/usage_asker.py` with `asking_in_a_process`, taking the home path, the calls file, the answer and the call length as arguments and rebuilding the replaced `urlopen`, the patched credential and anchor paths and the default config in the child; make `slow_endpoint` in the test file use the same endpoint function.
- [x] 1.5 Switch the test to `multiprocessing.get_context("spawn")`, keep one parked thread alive across the start, and join every process, terminating any still alive after its join.
- [x] 1.6 Add the `filterwarnings` entry to `[tool.pytest.ini_options]` in `pyproject.toml`, and grep `tests/` for any other `get_context("fork")` or `os.fork` use, moving it the same way.
