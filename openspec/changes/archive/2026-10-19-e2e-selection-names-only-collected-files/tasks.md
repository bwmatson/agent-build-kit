# Tasks

Acceptance: none — the selection is a pure function of the touched files and the profile, decided over temporary git repos and the fakes the e2e scope tests use; no stack or model is reached, so a scripted run would only repeat them.

Priority: 1

## 1. [agent-build-kit] [unit-test] A profile says whether its runner collects a file, and the own-test selection names only those

Priority: 1

Done when a toolchain profile answers whether its test runner collects a file by default; for python-uv that is a file named `test_*.py` or `*_test.py`, so a helper module under `tests/` and `conftest.py` are not collected while `is_test_path` is unchanged for them; node-npm answers as its `is_test_path` does; `_ids_for` names a touched test only when its file is collected, so `e2e_scope` and the own-test ids never name a helper; a unit that touched only files that are not collected has no runs, no lock and the existing skip line followed by the files left out. Estimate: about 120 changed lines.

- [x] 1.1 Test: `tests/pipeline/test_own_test_ids_collected.py` asserts, over a temporary git repo and the fakes `tests/e2e_scope_fakes.py` gives, that a unit adding `tests/integration/replay_unit_build.py` with a `def test_the_unit_is_built` and a driver `tests/integration/test_replay.py` has only the driver's id in the scope's `ids` and in the repeat command, and that the helper's id appears in neither.
- [x] 1.2 Test: the same file asserts a `test_*.py` module is named, a `*_test.py` module is named, a `test_*.py` outside a `tests/` directory is named, `tests/integration/conftest.py` holding a `def test_x` is not named, and a helper module in a nested `tests/` folder is not named.
- [x] 1.3 Test: the same file asserts the profile answers `collects_path` true for `test_x.py` and `x_test.py`, false for `conftest.py` and `helpers.py` under `tests/` (where `is_test_path` stays true), and that a node-npm project selects `src/a.test.ts` and `src/__tests__/b.ts` as it did and not `src/c.ts`, with `collects_path` equal to `is_test_path` for each.
- [x] 1.4 Test: the same file asserts a unit whose only touched test file is a helper has a scope with no runs and no ids, the reason beginning `e2e-test skipped: no e2e test added or changed` and naming the helper as not collected, takes no stack lock, and that a unit that touched no test at all gets the reason with nothing appended.
- [x] 1.5 Test: `tests/profiles/test_collects_path_not_is_test_path_callers.py` asserts the push gate (`pipeline/gate.py`), verify's deploy filter and the unit-test step still treat a helper module and `conftest.py` under `tests/` as test-side files, so `is_test_path` is not narrowed.
- [x] 1.6 Add the profile predicate to the `ToolchainProfile` protocol and both profiles, make the own-test selection name a touched test only when it holds, and say the left-out files when a unit ends with none; leave the other `is_test_path` callers as they are.

## 2. [agent-build-kit] [unit-test] The documents and the changelog say the own-test selection names only collected files

Priority: 1

Done when `docs/architecture.md` (the e2e-test narrowing paragraph) and `docs/toolchain-profiles.md` (the profile method table and each profile's section) say the own-test selection names only files the runner collects by default, that a helper module and `conftest.py` are not named, that a custom `python_files` or `testpaths` is not honoured, and that a unit touching only such files runs nothing and says so, and the changelog has one bullet under `## Unreleased`. Estimate: about 50 changed lines.

- [x] 2.1 Test: `tests/docs/test_collects_path_text.py` asserts `docs/toolchain-profiles.md` lists the new predicate in its table and in both profile sections, `docs/architecture.md` names the stated limit, and `CHANGELOG.md` has the bullet once under `## Unreleased`, in the style of the repository's existing doc-text tests.
- [x] 2.2 Update `docs/architecture.md` (the "narrowed to its own tests" bullet) and `docs/toolchain-profiles.md` (the table of profile methods and the python-uv and node-npm lists).
- [x] 2.3 Add one changelog bullet under `## Unreleased` as the repository's changelog section says: written for the person, one bullet, a two-space continuation, no unit names or numbers.
