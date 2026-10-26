# Design

## What was checked (origin/main and the open build-test branch)

- `tests/runtime_scratch.py`: for `claude_code` the setup is `runtimes_yaml=""`, an environment of the agent home and the account variables, and no
  command. `tests/live_build.py` (open work, group 15 of `tier2-tests-are-tagged-by-runtime`) writes the scratch `abk.yaml` with
  `{setup.runtimes_yaml}` appended, sets `ABK_CONFIG` to it, and `tick()` runs `abk tick` as a process in the scratch. The telemetry test writes its own
  scratch in `run_tick` until group 17 of that change moves it onto the shared setup.
- The outer pipeline runs the tests as `pytest` in the repo checkout with the process environment, the repos' credentials and `verify.env`
  (`Installation.verify_env`). It exports no path to its own `abk.yaml`; `ABK_CONFIG` is not set for the children.
- `settings.py` holds the per-machine, environment-only settings (`ABK_RUNTIME` and the others) as `pydantic-settings` fields.
- `pipeline/pause.py` writes `paused.json` in the state directory with `reason` and `kind` (`usage`, `rate_limit` or `network`); the tick's line
  `pausing until HH:MM — <reason>` is its wording. `usage_guard.decide_start` is the one place a usage start is refused.
- Attribution of a failed run (`pipeline/e2e.py`): the untouched tests of a failed run are run on the base; a test failing there too is
  `pre_existing`, a gate for other units; the rest are `own` or `broken` and go to the agent as feedback. `skipped` is counted apart and is not a failure.

## Inherit the numbers, or skip the guard

Both were considered; skipping is chosen.

- Inheriting needs a new channel from the outer pipeline to every test process (thresholds exported, or a path to the installation's `abk.yaml`
  that must then not be confused with the scratch's `ABK_CONFIG`), and the numbers are only a different default: a reading of 96% against a
  threshold of 95 pauses the inner tick as 91% against 70 did. The outer pipeline already judged the usage when it chose to run the test. A second
  judgement in the inner tick can only disagree with the first, a half-hour later, over a window that moved meanwhile.
- The tests assert the build, so a guard in the scratch is noise. Skipping it makes the run depend on what the test is about only.
- The cost: a setting that turns the guard off exists. It is environment-only, never in `abk.yaml`, announced on the tick's first line and in
  `abk status`, so it cannot be on unnoticed; it is not a configuration of the live pipeline.

## Skip or fail on a usage condition

The guard being off does not remove the account's own limit: Claude Code can refuse with a usage-limit message, which the runtime turns into a
`rate_limit` pause. A scratch tick can also pause for usage in a test that opted in. In both the test SKIPS, with a reason.

- A failure would be a `pre_existing` failure (it fails on the base as well) and hold other units behind a fix nobody can write, or feedback that sends
  the agent to rework code that is right. Usage is not a property of the code.
- A skip is counted in the run's summary, carries its reason in the output, and does not hold anything. The cost is that a unit whose own new
  build test skipped passes e2e-test without that test having run; the reason line says so, and the next scheduled run of the test is the proof.
- Only a `usage` or `rate_limit` pause skips. A `network` pause, no pause with no unit built, and a build failure with no pause stay failures.

## Where the code goes

- The switch is read in `usage_guard.decide_start` and the tick start, nowhere else, so "only the usage module refuses a usage start" keeps holding.
- The scratch default lives in `runtime_scratch()` because every scratch tick takes its environment from there; the skip lives in `tick()`
  of `live_build` and in the telemetry test's tick helper until that moves, both through one function.
