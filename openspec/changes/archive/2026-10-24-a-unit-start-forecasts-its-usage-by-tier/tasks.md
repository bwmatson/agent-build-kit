# Tasks

Acceptance: none — the forecast is a computation over recorded ledger rows, verdict records and a unit store, a check in the start decision, two records and two printed outputs, each proved by a unit-test over fixture ledgers, fake clocks, fake timers and temporary state directories; nothing a consumer drives is built beyond what those tests drive, and the live guard's behaviour with a real reading is the same code the tests call.

Priority: 3

## 1. [agent-build-kit] [unit-test] The history of a tier, its chances and its costs, and the forecast settings

Priority: 3

Done when `usage_forecast`, `usage_forecast_min_runs` and `usage_forecast_quantile` load with their defaults and ranges, the history of a review tier is gathered from verdict records and the ledger by unit id (never the ledger's test kind), a cell's chance and mean cost are computed with the stated fallbacks, the chance carries the quantile bound and is non-increasing in the round, and a tier or window with too little to go on is marked as the prior. Estimate: about 450 changed lines.

Needs: usage-is-estimated-from-recorded-cost group 5 — the forecast converts dollars with the `points_per_usd` its kept calibration holds (group 3), is added to the cost estimate it changes in `_estimates` (group 4), and replaces that estimate's flat allowance for a running unit with no record; its replay (group 5) is what the forecast's figures are checked against
Needs: units-are-triaged-by-review-tier group 3 — the tier a planner stored on the unit is what routes who is interrupted (a card for `light` and `full`, none for `auto`), so the tiers' steps differ only once it lands, and its verdict record keeps the planned tier the history is keyed by

- [x] 1.1 Test: in `tests/config/test_usage_forecast_settings.py`, with no settings `usage_forecast` is true, the minimum runs 10 and the quantile 0.9; a quantile of 0 or above 1, or minimum runs below 1, is refused naming the key; the keys are read beside the other `usage_*` settings and an unknown one is refused as before.
- [x] 1.2 Test: in `tests/pipeline/test_usage_forecast_history.py`, over a fixture ledger and verdict records, the history of `auto` holds the units whose verdict record is final and planned `auto` whatever test kind their rows carry, a unit with no final verdict is in no tier, rows of `plan`, `restack` and the other overhead nodes are not unit cells, and a unit's rows are counted once however many it has in a cell.
- [x] 1.3 Test: in `tests/pipeline/test_usage_forecast_cells.py`, a cell's chance is the share of the tier's units that ran it and its cost the mean of its calls; a cell under the minimum calls takes the mean over every model of the role, node and round and then of the node; a tier under the minimum units is marked prior, as is a window on the `units` basis (no points per dollar) and a unit with no stored tier; and the size bands split the tier at the median changed lines and are used only when both have the minimum units.
- [x] 1.4 Test: in `tests/pipeline/test_usage_forecast_rates.py`, a share of 3 of 10 at quantile 0.9 is above 0.3 and at most 1, the chance for 200 units at a 30% share is below that for 10 and above 0.3, a quantile of 0.5 gives exactly the observed share, a share of 0 of 10 has a non-zero bound, and the chances of a step's rounds are non-increasing.
- [x] 1.5 Add the three settings beside the other `usage_*` ones in `config.py` and the history, cell and rate computations in a module of their own under `pipeline/`.

## 2. [agent-build-kit] [unit-test] A unit's forecast, whole and for what is still to come

Priority: 3

Done when a unit about to start is forecast in dollars and, for each window, in points by the sum over its tier's cells, a unit's later gate is forecast at the step asked, what is still to come for a unit past some rounds is conditional on its having got there, and the prior is used where the spec says. Estimate: about 380 changed lines.

- [x] 2.1 Test: in `tests/pipeline/test_usage_forecast_unit.py`, over the `auto` and `full` fixture histories of the spec, the `auto` forecast is $2.55 and 6.4 points and the `full` forecast $3.42 and 8.6 points at 2.5 points per dollar, no rework cell is in the `auto` sum, and the review part of a `full` unit is $1.57 and not three rounds at the first round's cost.
- [x] 2.2 Test: in `tests/pipeline/test_usage_forecast_remaining.py`, a `full` unit at its review round 3 asks for that step at $0.40 and nothing after it, a unit that has run two review rounds has 6/18 of the round 3 cost still to come whatever it has spent, and a later gate's forecast is the cell asked at its mean and not its chance-weighted cost.
- [x] 2.3 Test: in `tests/pipeline/test_usage_forecast_prior.py`, a tier with nine units, a window on the `units` basis (no points per dollar) and a unit with no stored tier are each forecast at the window's flat per-unit allowance with the prior flagged, and a tier with enough units beside them is not.
- [x] 2.4 Add the unit forecast, with its split by role and node, beside the history module, taking the points per dollar and the flat allowance of each window as inputs.

## 3. [agent-build-kit] [unit-test] Running units and due plan calls and tracks reserve what they will cost

Priority: 3

Done when the guard records a step row when it admits a step, a unit with an unfinished step contributes the unfinished share of its cell's cost, a plan call due and a track whose timer fires before a window resets reserve their expected cost for that window and release it when their row is written, and a timer that cannot be read reserves nothing and is reported. Estimate: about 420 changed lines.

- [x] 3.1 Test: in `tests/pipeline/test_usage_forecast_record.py`, admitting a unit's first step appends a forecast row and a step row under the lock, a later step only a step row, the same ask twice one step row, a record that cannot be written logs and does not refuse the start, a half-written last line is skipped, and with `usage_forecast` off nothing is written.
- [x] 3.2 Test: in `tests/pipeline/test_usage_forecast_running.py`, with a fake clock, a unit admitted on an estimate with no ledger row and a step row adds its remainder and not the flat allowance as well, a $1.00 cell of ten minutes' mean duration and a step row four minutes old a running unit adds $0.60, twenty minutes old one tenth of $1.00, a step row with a later ledger row of the same unit, node and round adds nothing, the unit asking is not counted, and a running unit with no step row adds nothing and is counted as unrecorded.
- [x] 3.3 Test: in `tests/pipeline/test_usage_forecast_reservations.py`, with fake timers and a fake ledger, a track whose timer fires before the session reset reserves its mean cost for both windows and one firing after it for the weekly window only, a plan call due reserves the `plan` cell's mean, `track_propose` is added with a track that proposes, a reservation is released once the track's ledger row is written, and unreadable timers reserve nothing and say so.
- [x] 3.4 Add the forecast record (its row shapes and reader) and the step rows written where the guard admits, the running-unit remainder, and the reservations with a reader of the installed timers' next elapse, as modules under `pipeline/` that `usage_guard.py` calls.

## 4. [agent-build-kit] [unit-test] The start decision applies the forecast and says what dominates

Priority: 3

Done when a start is refused for a window when its estimate plus the forecast and the margin is not under the threshold, on an estimate and on a reading, the reason names the window, the forecast and the role and node that dominate, the unit is stopped as any refusal is, and the emergency lane and the cap on starts behave as before. Estimate: about 520 changed lines.

- [x] 4.1 Test: in `tests/pipeline/test_usage_forecast_decision.py`, at a held reading of 67% with a threshold of 80 and a margin of 5 an `auto` unit is allowed and a `full` unit refused, on an estimate and on a live reading, a refusal on the reading's own threshold is unchanged when the forecast is zero, a weekly estimate of 86 under 92 refuses a unit forecast at two weekly points naming the weekly window, and `usage_forecast` false or the guard off decides as before.
- [x] 4.2 Test: in `tests/pipeline/test_usage_forecast_reason.py`, the refusal's reason holds the estimate's text, the window, the forecast in points and the role, node and round with the most points, names a reservation when it is the largest, says when the prior was used, and the refused unit is stopped with its resume time as before.
- [x] 4.3 Test: in `tests/pipeline/test_usage_forecast_lane_and_cap.py`, a priority-0 `full` unit is refused and a priority-0 `auto` unit allowed exactly as at priority 3 with the emergency lane having room, a lane unit that is running is a running unit for another's forecast, with a cap of three and three admitted a fourth that fits is refused for the cap, and a unit the forecast refused does not count towards it.
- [x] 4.4 Test: in `tests/pipeline/test_usage_forecast_asks.py`, the round-level ask with no unit forecasts the lowest tier among the startable units, a track's or the planner's ask is forecast as one call at its mean, and a unit's later gate is judged on the step asked and not its whole path.
- [x] 4.5 Add the forecast to `WindowEstimate` and the estimate's `ample` test, the same check after the reading has allowed on the non-estimate path of the decision, and the unit's tier, size and step passed to the guard where the gate and the tracks name the unit they start.

## 5. [agent-build-kit] [unit-test] The status command prints the forecast beside the estimate

Priority: 3

Done when `abk status` prints a forecast line after each account's estimate line, with each tier's forecast and the number of units it rests on or the prior, the running units' remainder and the reservations, and nothing when forecasting is off or the runtime has no window. Estimate: about 260 changed lines.

- [x] 5.1 Test: in `tests/cli/test_status_usage_forecast.py`, over fixture histories, one running unit and a reserved track, the line gives each tier's session and weekly points with its unit count, marks a tier with five units as the prior, shows the running unit's remaining points and the unrecorded count, shows the reservation and whether the timers were read, appears after the estimate line, and is absent with `usage_forecast` false and for a runtime with no usage window; no call is made.
- [x] 5.2 Add the line to the account's usage lines in `cmd_status`, built from the forecast modules, without a call.

## 6. [agent-build-kit] [unit-test] The report groups by review tier and shows forecast against actual

Priority: 3

Done when `abk report --by tier` groups by the review tier planned for each unit and shows each tier's units, forecast, spent, ratio, units over their forecast and spend by role and node, unforecast units are shown apart, and every other grouping is as it was. Estimate: about 350 changed lines.

- [x] 6.1 Test: in `tests/pipeline/test_usage_report_by_tier.py`, over fixture rows, verdict records and forecast rows, `auto` units forecast at $2.55 that spent $2.00, $2.60 and $3.40 give $7.65 forecast, $8.00 spent, 1.05 and one over, a unit with no forecast row is counted as unforecast and left out of the ratio, a unit with no tier is under `(none)`, rows with test kinds `unit-test` and `e2e-test` make no group of those names, and a forecast recorded under other settings is summed as recorded.
- [x] 6.2 Test: in `tests/cli/test_report_by_tier.py`, `abk report --by tier` prints the table and `--json` the same figures, the choices include `tier`, and `--by node` prints what it did before.
- [x] 6.3 Add the `tier` grouping with its forecast columns to the report module and its choice to `abk report`.

## 7. [agent-build-kit] [unit-test] The documents and the changelog describe the forecast

Priority: 3

Done when the documents, the shipped config skill and the changelog say what the forecast is, what it reads and writes, how it is set and what it leaves alone. Estimate: about 160 changed lines.

- [x] 7.1 Test: in `tests/docs/test_usage_forecast_documented.py`, the three settings are named in `docs/configuration.md` and the shipped `abk-config` skill, `abk report --by tier` in `docs/cli.md`, and `docs/architecture.md` describes the forecast where the estimate is described.
- [x] 7.2 Describe the forecast in `docs/architecture.md` beside the estimate and its cap, the settings in `docs/configuration.md` and the `abk-config` skill's block, `abk report --by tier` and the status line in `docs/cli.md`, the recorded files in the state-directory description, and an entry under Unreleased in `CHANGELOG.md`.
