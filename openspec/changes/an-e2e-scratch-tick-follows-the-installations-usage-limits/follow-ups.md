## From `an-e2e-scratch-tick-follows-the-installations-usage-limits/1`

- tests/pipeline/test_usage_guard_switch.py:60 — The 'unset' case (value None) does not unset anything: it tests whatever `settings.usage_guard` the test process was imported with.
- src/agent_build_kit/pipeline/usage_guard.py:1292 — `settings.usage_guard == "off"` is tested in two places (`guard_off_line` and `decide_start`), and the text 'usage guard off (ABK_USAGE_GUARD)' is written twice.

## From `an-e2e-scratch-tick-follows-the-installations-usage-limits/2`

- `skip_on_usage_condition` in tests/usage_condition.py imports `branch_on_remote` from tests/scratch_tick.py inside the function to get around a circular import, because scratch_tick imports usage_condition. Moving `branch_on_remote` into a module that both of them import, or moving the skip into scratch_tick, would remove the deferred import and its noqa.
