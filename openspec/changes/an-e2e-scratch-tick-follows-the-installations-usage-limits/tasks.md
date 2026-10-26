# Tasks

Acceptance: none — the setting, the start decision and the skip are decided by a fake usage reading, a hand-made pause marker and the scratch setup read as data; no consumer-facing behaviour is built, and the next e2e-test run of the Claude Code variants is the live confirmation.

Priority: 2

## 1. [agent-build-kit] [unit-test] A process started with the usage guard off takes no usage reading and never pauses for usage

Done when `ABK_USAGE_GUARD=off` makes the start decision go ahead with no reading, no threshold, allowance or estimate, the tick says so on its first line and `abk status` shows it, any other value is refused, and nothing in `abk.yaml` can set it. Estimate: about 220 changed lines.

- [x] 1.1 Test: `tests/pipeline/test_usage_guard_switch.py` with a fake reading that returns 91 percent against a threshold of 70 asserts the decision is "go" when the setting is `off` and the fake reading function is never called, and is a refusal naming 91 and 70 when the setting is unset or `on`; and that an unreadable reading, a stale one and an exhausted allowance do not stop a start when off.
- [x] 1.2 Test: `tests/test_settings_usage_guard.py` asserts `ABK_USAGE_GUARD` accepts `on` and `off`, defaults to `on`, refuses another value naming the setting and both values, and that `usage_guard` as a key of `abk.yaml` is refused as an unknown key.
- [x] 1.3 Test: `tests/cli/test_tick_usage_guard_off.py` asserts a tick with the setting off prints `usage guard off (ABK_USAGE_GUARD) — no usage is read and no start is held for usage` before anything else, takes no reading, writes no usage pause marker, and `abk status` shows the same line; with it on, neither line appears.
- [x] 1.4 Add the setting to `settings.py` as an enum of `on` and `off`, return early from `decide_start` when it is off, and print the two lines in the tick and the status.

## 2. [agent-build-kit] [unit-test] A Claude Code scratch installation is made with the guard off, and a test about the guard opts in

Done when the scratch setup for `claude_code` carries `ABK_USAGE_GUARD=off` in its environment, `usage_guard=True` leaves it out, and the ACP setup is unchanged. Estimate: about 110 changed lines.

- [x] 2.1 Test: `tests/integration/test_runtime_scratch_setup.py` asserts the `claude_code` setup has `ABK_USAGE_GUARD` equal to `off` in `env` and still no `runtimes_yaml` and no `ABK_RUNTIME`, that `runtime_scratch("claude_code", ..., usage_guard=True)` has no `ABK_USAGE_GUARD` in `env`, that the ACP setup has neither the variable nor a change in its `runtimes_yaml`, and that a variable set in the process of the test run is overridden by the setup's value.
- [x] 2.2 Add the `usage_guard` parameter (default `False`, meaning the guard is skipped) to `runtime_scratch` in `tests/runtime_scratch.py` and set the variable there for the Claude Code runtime, so that every scratch tick takes it from its one setup.

## 3. [agent-build-kit] [unit-test] A scratch tick that paused for usage skips its test with the reading and the threshold

Needs: tier2-tests-are-tagged-by-runtime group 17 — the telemetry test's tick helper moves onto the shared scratch, which comes after group 15 that creates `tests/live_build.py` and its `tick`

Done when a scratch tick that built no unit and left a usage or rate-limit pause marker ends its test as a skip whose reason names the reading and threshold or the limit message, a network pause and a tick with no pause stay failures, and the build, graph and telemetry tests all go through the one function. Estimate: about 170 changed lines.

- [x] 3.1 Test: `tests/test_usage_condition.py` with a state directory holding a `paused.json` of kind `usage` and reason `session usage at 91% (threshold 70%, live)` asserts the function skips with a reason that contains `91%`, `70%`, `usage is an environment condition` and `the build was not attempted`; a `rate_limit` marker skips with the marker's reason; a `network` marker does not skip; no marker does not skip; an expired marker does not skip; and a marker next to a built unit (the branch is on the remote) does not skip.
- [x] 3.2 Test: `tests/integration/test_usage_condition_callers.py` asserts `live_build.tick` and the telemetry test's tick helper each call the function once after the process ends, and that the failure text of a tick that built nothing without a pause is unchanged.
- [x] 3.3 Add the function (a module in `tests/`) that reads the scratch's pause marker with `pipeline/pause.py`, and call it from `tick()` in `tests/live_build.py` and from the telemetry test's helper.

## 4. [agent-build-kit] [unit-test] The documents say how a scratch tick treats usage

Done when the documents name the setting, say it is for scratch installations and never read from `abk.yaml`, and say a usage condition skips a live test. Estimate: about 60 changed lines.

- [x] 4.1 Test: `tests/docs/test_usage_guard_switch_documented.py` asserts `docs/configuration.md` names `ABK_USAGE_GUARD` with its two values and says it is not an `abk.yaml` key, `docs/cli.md` shows the tick's first line, the `abk-pipeline` skill says a live test skips on a usage pause and why, and the changelog has an entry.
- [x] 4.2 Update `docs/configuration.md`, `docs/cli.md`, the `abk-pipeline` skill and the changelog.
