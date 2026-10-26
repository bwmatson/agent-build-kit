## Context

Code at agent-build-kit `origin/main` (872fa344).

- **Where ids are built.** `e2e_scope` (`pipeline/wiring.py:2301-2358`) returns the whole marker for a dev stack script, a scheduled run, the `full` setting, a profile that does not implement `RepeatsTests`, no base, or an unlistable diff; otherwise it calls `touched_tests` once (`:2335`) and `_ids_for(touched, cwd, where, toolchain)` per project (`:2345`), turns the ids into repeat commands with `toolchain.repeat_command`, and reports `e2e-test skipped: no e2e test added or changed` when no run results (`:2353-2357`). `own_test_ids` (`:3338-3350`) is the same selection for callers that want the ids without running them.
- **`_ids_for`** (`:1548-1557`): `f"{relative}::{name}"` for each `(path, name)` with `toolchain.is_test_path(path)` and the path under `where`. Its docstring says "Only test files"; the python-uv meaning of "test file" is the problem.
- **`is_test_path`** is in the `ToolchainProfile` protocol (`profiles/base.py:174`), python-uv at `python_uv.py:323-325` and node-npm at `node_npm.py:391-393`. Its other callers are `pipeline/gate.py:90` (classifying paths of a push), `pipeline/verify.py:88` (a test path deploys nothing), `graph/nodes.py:944` (the unit-test node's test/source split), `python_uv.py:621` (stub violations) and, inside the node profile, `node_npm.py:217` and `:402`. All of them mean "a test-side file, edited with the tests" and rightly count helpers and `conftest.py` as test-side.
- **pytest and explicit ids.** Collection by default takes `python_files = test_*.py *_test.py`; a path given on the command line is imported whatever its name, so `path.py::test_x` runs a test from a module the suite never collects. That is what happened to `replay_unit_build.py`.

## Decisions

- **A new predicate, not a change to `is_test_path`.** The two questions differ: "is this file part of the test side" (do not deploy it, do not require a stub, run the unit-test step over it) and "will the runner collect it". Changing `is_test_path` would put `conftest.py` and helpers in the source set for the gate and verify, which would then count them as code to deploy. The new method sits beside `is_test_path` in the `ToolchainProfile` protocol (`profiles/base.py`) so every profile answers it. The test double profiles in `tests/` subclass `PythonUvProfile` or the real profiles and inherit it; the protocol-conformance tests list it.
- **python-uv: the file name only.** `^(test_.*|.*_test)\.py$` on the last path component, with no condition on the directory: a `test_x.py` outside `tests/` is collected by default pytest and still is named (it already was, through the name branch of `is_test_path`). `conftest.py` is dropped from the name pattern here though `_TEST_FILE` has it: a fixture file holds no collected test, and a `def test_*` in it is a helper.
- **node-npm: `collects_path` is `is_test_path`.** Vitest's default include is the `.test`/`.spec` rule the profile already uses; a `__tests__` directory file is the one extra the profile accepts. Behaviour is therefore unchanged; the method returns what `is_test_path` returns, so the node scenarios keep passing.
- **Filtering lives in `_ids_for`, not in `touched_tests`.** `touched_tests` is a record of which tests the branch added or changed, read by other callers (the changed-test sets in `pipeline/wiring.py` around `_changed_tests`, `:3300-3335`); narrowing it would change them. `_ids_for` is where a path becomes a runner-selectable id, so it is where "the runner would not collect this" belongs. It takes the toolchain already, so the signature does not change.
- **A helper-only unit selects nothing, and says what it skipped.** The result is the existing empty scope: no run, no lock, status "no e2e test ran". A unit whose only touched `tests/` files are helpers is common (a driver and its helper are often in one group, but a rework may touch only the helper). The log line names the touched files that were left out ("not collected by the suite: tests/integration/replay_unit_build.py") when any, so a person sees why the unit ran nothing instead of suspecting a missing test. No new reason string is read by anything: the existing skip line stays as the prefix.

## Stated limit

The kit never reads pytest's `python_files`, `testpaths` or `-o` overrides. A repo that collects `check_*.py` through its own configuration has its tests unnamed by the own-test selection (not selected, not failing) and they run in the whole marker run only; a repo that narrows `python_files` below the default keeps naming `*_test.py` helpers it does not collect. Both are the default-rule assumption, written down in the spec.

## Fuller fix, not built

Confirm the ids against the runner: after `_ids_for`, call the profile's `list_tests(command, selection, run=..., among=ids)` (`python_uv.py:505`, `profiles/base.py:212`), which runs `pytest --collect-only` with the repo's own configuration and returns only the ids the suite collects. That honours `python_files` and `testpaths` and would make `collects_path` unnecessary, at the cost of a collection run per unit before the lock and a failure mode (a listing that fails returns None) the narrowing must treat as "run whole". It is left for a change that owns that cost.

## Risks

- A repo with an unusual but legal naming (`TestFoo.py`) loses own-test narrowing for it; the whole marker run still runs it, so a fault is found later, not missed.
- The skip line changes only by an appended list of left-out files; nothing in the repo matches the line's exact text beyond its prefix, and a test asserts the prefix is intact.
