## Context

Code at agent-build-kit `origin/main` (3063b9d0). Read first: `.github/scripts/warm-openspec.sh`, `.github/workflows/ci.yml:61-88`, `tests/time_limit.py`
(`23`, `37`, `60-64`) and `tests/test_ci_openspec_step.py` (its `Fetch` helper runs the real script with a fake `npx` on `PATH`).

## Decisions

- **300 s, from an env var.** `OPENSPEC_ATTEMPT_TIMEOUT` follows `OPENSPEC_RETRY_DELAY` (`warm-openspec.sh:9`), so a test can pass a small value and the
  workflow needs no change for the default. Rejected: more attempts (each failed attempt wipes the cache, and the log shows three timeouts either way); a
  longer delay (the failures were slow downloads, not a registry that came back after a pause).
- **`timeout-minutes: 20`.** The worst case is 3 x 300 + 10 + 20 = 930 s, 15.5 minutes. 20 leaves four and a half minutes for `uv run` start-up inside the
  step. A step limit equal to the worst case would cut the last attempt's own message.
- **A per-test marker, because none exists.** The time-limit plugin has two limits chosen by the `local_stack` marker (`time_limit.py:62-64`); there is no way
  to give one test more time. Choices weighed: raise `--test-time-limit` for the integration step (widens every test of the tier, and the existing
  `test_the_test_step_still_runs_pytest_integration_with_no_time_limit_option` pins the step command), give the test `local_stack` (changes its tier and the
  limit to 30 minutes), or add `time_limit(seconds)`. The marker is about eight lines in `_under_limit`: `item.get_closest_marker("time_limit")` and its first
  argument replace the default for that item. It does not touch the e2e limit: a test with both markers keeps the e2e limit.
- **The vitest test gets 180 s**, three times the 60 that the download overran, and well under the 300 s of the fetch.

## What this does and does not fix

It helps when the registry is slow: a download that took 2-4 minutes now finishes, in both places. It does not help when the registry is unreachable or
refuses the request; three 300 s attempts then fail after 15 minutes instead of 6, which is a slower failure of the same kind. There is still no lockfile,
so each run fetches the CLI and vitest from the registry (declined for now). The retry of a failed setup step by the pipeline is listed under "Not in this
change" in the proposal, with the lockfile install as a possible later hardening.

## Risks

- A slower failed run when npm is down: accepted, and bounded by the step limit.
- The marker could be read as a way to lengthen any slow test. The spec says it is for a test whose time is outside the test's control, and the plugin test
  pins that it changes only the item that carries it.
