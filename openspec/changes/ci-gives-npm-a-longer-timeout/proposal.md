## Why

Code at agent-build-kit `origin/main` (3063b9d0).

**The fetch step.** `.github/scripts/warm-openspec.sh` runs `timeout 120 npx --yes "$spec" --version` (`:14`) up to `attempts=3` times (`:8`), removing
`$cache/_npx` and sleeping `delay * attempt` seconds between them (`:18-20`, delay 10 by default, `:9`). On 2026-10-22 all three attempts hit the 120 s limit
(run 39711881837, 02:32-02:38 UTC; run 39714359908, 02:59), while the same package fetched at 03:07 and `npm view` works locally: the registry was slow, not
down. The step in `.github/workflows/ci.yml:78-86` has `timeout-minutes: 10`.

**The vitest test.** `tests/integration/test_node_npm_red_command_vitest.py:24-48` runs `npx vitest` (with `npm_config_yes=true`) in an empty directory, so it
downloads vitest at test time. It failed with "test exceeded the time limit of 60 seconds" in runs 39666378362 and 39711335246. The 60 comes from
`DEFAULT_TEST_TIME_LIMIT = 60` in `tests/time_limit.py:23`, a plugin loaded by `tests/conftest.py:51`. It applies to every test that does not carry the
`local_stack` marker (`:62-63`), and so to `integration`-marked tests; `pyproject.toml:84-100` sets no limit of its own. The only per-test choice today is the
`local_stack` marker, which would also select the test into a different tier. So 60 s is not set for this test and is right for most others; a global rise
for `integration` would loosen every test of that tier to fix one.

## What Changes

- `warm-openspec.sh` reads its per-attempt limit from `OPENSPEC_ATTEMPT_TIMEOUT`, default 300 (seconds), in place of the literal 120. Three attempts and the
  delay are unchanged.
- The step's `timeout-minutes` goes from 10 to 20: 3 x 300 s plus the 30 s of delays is 15.5 minutes, and the rest is start-up margin.
- `tests/time_limit.py` reads a `time_limit(seconds)` marker: a test that has it is held to that many seconds on setup, call and teardown, and every other
  test and the flags are as before. The marker is registered in `pyproject.toml`. The vitest test carries `time_limit(180)`.
- The tests of the script and of the step are updated; one changelog bullet.

## Not in this change

- **A lockfile, or a `npm ci`-style install of the pinned CLI.** Declined for now; it would remove the on-demand download, and may come later as hardening.
- **Re-running a failed setup step.** A failing check whose failed step is a setup step (this fetch) being re-run by the pipeline, instead of reworked by an
  agent, is a follow-up in the pipeline and not made here.
