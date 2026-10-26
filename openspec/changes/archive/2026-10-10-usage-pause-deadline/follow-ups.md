## From `usage-pause-deadline/1`

- The rate-limit branch of `_build_unit` (src/agent_build_kit/cli/pipeline.py:2042) now goes through `pause_line`, but no test reaches it through its caller with a non-UTC TZ. A tick test where the runner raises the rate-limit error under `TZ=Asia/Kolkata` would check that the 'rate limited — pausing until HH:MM' line is in local time and has no 'UTC', like the new usage-pause test does.
- Round 1's optional point 1.5 was not done: a written stale-reading pause lasts the stale retry plus RESUME_GRACE, so about 7 minutes by default. The docs and the changelog say 'five by default'. Either reword them to 'five minutes plus the grace', or skip the grace for a stale pause in a later unit.

## From `usage-pause-deadline/2`

- Failure-cause log suppression is per process and reset only by `cmd_tick`. A long-lived process such as `abk serve` never logs a recurring cause again. Consider a time-based reset.
- `wiring.build_may_start` is now unused in src and duplicates the runtime short-circuit in `build_usage_gate`. Remove it or reuse it.
- src/agent_build_kit/pipeline/usage_guard.py:82 — `_logged_failures` is only cleared by `cmd_tick`. A long-lived process that reads usage but never ticks, such as `abk serve` showing status, logs each cause once in its whole lifetime, not once per tick.
- src/agent_build_kit/pipeline/wiring.py:1233 — `build_may_start` has no caller in src now that `build_runner` uses `build_usage_gate`, and `build_usage_gate.may_start` repeats its runtime short-circuit.
## From `usage-pause-deadline/3`

- A round refused for usage still polls, and a merge it finds can restack and run the conflict resolver, a model call that does not ask the guard. Either gate the resolver on the guard, or reword the `run_round` comment that says only planning spends a model call.
- In tests/pipeline/test_cli_pipeline.py, replace the two `clear_pause` stubs with `window_spent_after_the_first_round`, so the guard in those tests refuses the rounds after a paused build as a real one would.
- src/agent_build_kit/cli/pipeline.py:826 — The `run_round` comment and docstring say planning is the step that spends a model call, so only planning stays behind the guard. But a round refused for usage now polls, and a merge the poll finds restacks the units above it (`events.py` around line 1475, `move(...)`). That restack can run the conflict resolver, which is a model call that does not ask the usage guard.
- tests/pipeline/test_cli_pipeline.py:370 — `test_a_pause_resumes_when_the_window_resets` and `test_a_usage_pause_takes_its_reason_and_time_from_its_fields` stub out `clear_pause` entirely. They do this so a later round, under a guard that always allows, does not clear the marker the build wrote. The same file already adds `window_spent_after_the_first_round`, which makes the guard behave as a real one does instead.
## From `usage-pause-deadline/4`

- In `read_live_usage`, a process that finds the refresh lock held and is served the kept reading counts a `wait` but writes no line to `usage-calls.jsonl`. docs/architecture.md says that file holds 'one line per call or cache answer'. `serve()` records an `outcome="cache"` line, and the waiter path could record one the same way so the audit file matches the doc.
