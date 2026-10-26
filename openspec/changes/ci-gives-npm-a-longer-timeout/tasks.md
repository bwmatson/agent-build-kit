# Tasks

Acceptance: none — the script is run with a fake `npx` and `timeout`, the workflow is read as YAML, and the plugin is driven in a child pytest, as their tests do today; nothing a consumer drives is built.

Priority: 1

## 1. [agent-build-kit] [unit-test] The OpenSpec fetch gives each attempt 300 seconds and the step 20 minutes

Priority: 1

Done when `warm-openspec.sh` passes `${OPENSPEC_ATTEMPT_TIMEOUT:-300}` to `timeout`, keeping three attempts, the delay and the cache removal, and `ci.yml`'s fetch step has `timeout-minutes: 20`. Touches `.github/scripts/warm-openspec.sh`, `.github/workflows/ci.yml`, `tests/test_ci_openspec_step.py`. Estimate: about 60 changed lines.

- [x] 1.1 Test: in `tests/test_ci_openspec_step.py`, put a fake `timeout` beside the fake `npx` in `Fetch.run` (it records its first argument, then execs the rest); the default run records 300 for every call, `OPENSPEC_ATTEMPT_TIMEOUT=7` records 7, and the existing retry and failure cases still see three calls.
- [x] 1.2 Test: in the same file, the fetch step's `timeout-minutes` is at least 16 (3 x 300 s + 30 s of delays, rounded up) and the script text no longer holds the literal `timeout 120`; the existing step-position and no-pin tests are unchanged.
- [x] 1.3 Edit `warm-openspec.sh` to read the variable (default 300, beside `OPENSPEC_RETRY_DELAY`) and use it in the `timeout` call, and `ci.yml` to set `timeout-minutes: 20` and say in its step comment that a slow registry is what the limits are for.

## 2. [agent-build-kit] [unit-test] The vitest test carries a 180-second time limit of its own, and the changelog says so

Priority: 1

Done when `tests/time_limit.py` reads a `time_limit(seconds)` marker, `pyproject.toml` registers it, the vitest integration test carries `time_limit(180)`, and `CHANGELOG.md` has one bullet under `## Unreleased` (the changelog section of AGENTS.md applies: CI runs are what a contributor sees). Touches `tests/time_limit.py`, `tests/test_e2e_time_limit.py`, `pyproject.toml`, `tests/integration/test_node_npm_red_command_vitest.py`, `CHANGELOG.md`. Estimate: about 70 changed lines.

- [x] 2.1 Test: in `tests/test_e2e_time_limit.py`, over its generated files and child pytest, a `time_limit(5)` test taking 2 s under `--test-time-limit 1` passes, a `time_limit(1)` test taking 3 s fails with "test exceeded the time limit of 1 seconds", an unmarked test taking 2 s beside them still fails at 1 s, and a `local_stack` test with the marker keeps the e2e limit.
- [x] 2.2 Test: in `tests/integration/test_node_npm_red_command_vitest.py`'s neighbour `tests/test_vitest_test_time_limit.py`, collecting that file reports `time_limit` with the argument 180 on the vitest test (read with `get_closest_marker`), and `--strict-markers` accepts it.
- [x] 2.3 Edit `_under_limit` in `tests/time_limit.py` to use the marker's first argument as the limit for a non-e2e item, register `time_limit(seconds)` in `pyproject.toml`'s `markers`, add `@pytest.mark.time_limit(180)` to the vitest test with a one-line reason (it downloads vitest), and add one bullet under `## Unreleased` in `CHANGELOG.md` (CI's npm fetches wait up to 300 s per attempt, the step allows 20 minutes, and a test can carry its own time limit), in the file's format.
