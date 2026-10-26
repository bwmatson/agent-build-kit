## From `a-unit-start-forecasts-its-usage-by-tier/1`

- src/agent_build_kit/pipeline/usage_forecast_history.py:52 — StepCost is used for two things: a step's mean, where role and round are always set, and a node's mean, where both are None. forecast_step then writes `s.role or ""` for a role that is never None, and builds the node fallback's Part with role="".
- src/agent_build_kit/pipeline/usage_forecast_unit.py:157 — forecast_remaining treats a missing last_round as 'past history' only when it is at or above the node's lowest recorded round, so a gap inside the recorded rounds also gives nothing to come.

## From `a-unit-start-forecasts-its-usage-by-tier/3-s1`

- src/agent_build_kit/pipeline/usage_forecast_running.py:18 — `record_time` is a new named helper that parses a ledger record's `at` and skips one that does not parse. `usage_ledger.spend_times` (line 361) and `spend_costs` (line 383) already do the same parse-and-skip inline, without the time-zone check.

## From `a-unit-start-forecasts-its-usage-by-tier/3-s2`

- src/agent_build_kit/cli/pipeline.py:2172 — Line 2172 (the per-unit refusal check) and line 1836 (lifting a pause) call `_account_decision(each, decided)` with no ask. When `_start_decision` is allowed by an earlier account it stops there, so a later account is not in `decided` yet and is asked with an empty `Ask`, which is not forecast.

## From `a-unit-start-forecasts-its-usage-by-tier/5`

- The rework also changed `abk report --by tier --since` so that it picks units by date but sums each picked unit's whole spend (`_whole_units`). The spec doesn't say how `--since` interacts with forecast against actual. The choice is sensible, but a reviewer should confirm it is intended and that `docs/` describes it.
- `held_forecast_line` now reads the installed timers only when a window has a reset ahead, the same rule `_ahead` uses. Before, it read them whenever a root was active. A status line for an installation whose resets are all in the past will now say the timers were not read. That matches the start decision, but it is a visible change to the status line.
- src/agent_build_kit/pipeline/usage_guard.py:1775 — `_forecast_row(...)` and the `read_record(path)` that decides `first` both run outside `record_admission`'s try/except, so an error while the forecast row is being built would escape `decide_start` after the decision was already made.

## From `a-unit-start-forecasts-its-usage-by-tier/7`

- docs/cli.md:131 — The status sentence says the `forecast:` line shows what is held back "for tracks and the plan call". But `forecast_line` calls `reserve(..., plan_due=False, ...)` (`usage_forecast_status.py`), so status never shows a plan-call reservation. The wording follows what round 1 asked for.
