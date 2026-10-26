## Why

The unit `tier2-replays-unchanged-calls/3` failed its e2e-test step on `tests/integration/replay_unit_build.py::test_the_unit_is_built`. That module is a branch-only helper: its name does not match `test_*.py`, so the repo's suite never collects it, and its test needs environment variables that a driver test sets. The pipeline named it by node id anyway, pytest collected the explicit id from a non-`test_*.py` module (pytest does that for a path given on the command line), and it ran without its environment and failed.

The cause is in how a unit's own tests are chosen (code at agent-build-kit `origin/main`, 872fa344):

- `e2e_scope` takes `touched_tests(cwd, base)` (`src/agent_build_kit/pipeline/wiring.py:2301`, `:2335`; `touched_tests` at `:3325`), the `(file, test)` pairs for each `def test_*` the branch added or changed, and for each project calls `_ids_for` (`:2345`, definition `:1548-1557`). `_ids_for` keeps a pair when `toolchain.is_test_path(path)` is true. `own_test_ids` (`:3338`) reaches the same filter.
- `PythonUvProfile.is_test_path` (`src/agent_build_kit/profiles/python_uv.py:323-325`) is true for anything with a `tests` directory above it, or a file name matching `_TEST_FILE` (`:46`, `^(test_.*|.*_test|conftest)\.py$`). It answers "is this a test-side file", which is the right question for the verify, push-gate and stub checks, and the wrong one for "will the suite collect it".
- The kit never reads pytest's `python_files` or `testpaths`, so nothing between the touched file and the command line asks whether pytest would have collected it.

## What Changes

- **A profile predicate `collects_path(path)`.** It says whether the profile's test runner collects the file by its default rules. For python-uv: the file name matches `^(test_.*|.*_test)\.py$`, wherever the file is. For node-npm: the same answer as its `is_test_path` (a `__tests__` directory, or `.test`/`.spec` before the extension), since vitest's default include and that test are the one rule there.
- **The own-test selection uses it.** `_ids_for` keeps a touched test only when `toolchain.collects_path(path)` is true (and the file falls under the project). A helper module under `tests/` with a `def test_*`, `conftest.py` and a file of the unit's under `tests/` that does not match are never named.
- **A unit that touched only such files selects nothing.** The scope has no ids, the unit runs no e2e command, takes no lock and logs the existing `e2e-test skipped: no e2e test added or changed` line, as for a unit that touched no test. The log also says which touched files were not named, so the skip is not mistaken for a missing test.
- **`is_test_path` is unchanged and its other callers keep it**: the push gate's test-or-source split (`pipeline/gate.py:90`), verify's deploy-relevant-file filter (`pipeline/verify.py:88`) and the unit-test graph node's split (`graph/nodes.py:944`) all still mean "a test-side file".
- **A stated limit.** A custom `python_files` (or `testpaths`) in a repo's pytest configuration is not read, so a repo whose suite collects `check_*.py` has those tests left unnamed by the own-test selection, and they run only in the whole marker run. A fuller fix is described in the design and not built here.

No change to the wire, to `abk.yaml`, to the whole-marker run, to splits or to the node profile's behaviour.
