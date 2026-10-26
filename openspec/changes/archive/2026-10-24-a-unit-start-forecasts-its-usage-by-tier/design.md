# Design

Citations are to agent-build-kit `origin/main` at 460cad10.

## Context

**Where the start decision is made today.** There are three asks, all through `decide_start` (`pipeline/usage_guard.py:1339`), which
wraps `_decide_start` (`:1355`):

- the tick's round-level ask, `_start_decision(accounts)` (`cli/pipeline.py:1408`, called at `:1532`), with no unit named;
- the **gate before every agent step of a unit**, `Runner.gate` under `starting(self.unit.id)` (`graph/nodes.py:314-315` for each
  node in `AGENT_NODES`, `:497`) — not only before a unit's first step, so a refusal pauses a unit between steps;
- a track's ask, `starting(f"track:{phase}")` in `has_headroom` (`tracks/runner.py:790`, `:923`), and the planner's, which is the
  round-level ask when `_needs_planning` (`cli/pipeline.py:1388`) is true.

`_decide_start` answers from a Claude Code cache block, a held reading judged by `may_start_unit` (`:1020`), or a fresh read; when the
endpoint cannot be asked it falls back to `_decide_on_estimate` (`:1251`), which gets each window's `WindowEstimate` from `_estimates`
(`:1204`) and `estimate_usage` (`:1154`): reading plus allowance times units that spent or were admitted since, allowed only when
`estimate + margin < threshold` (`WindowEstimate.ample`, `:1140`), then capped at `usage_estimate_max_starts` per reading (`:1269`,
`config.py:298`) and recorded by `_record_admitted` (`:1284`). `may_start_unit` and the estimate never see the unit being admitted:
only its id, through the `_starting` context variable (`:871`).

**What a unit's cost is made of.** The ledger (`UsageRecord`, `pipeline/usage_ledger.py:100`) has role, node, round, model, `resumed`,
`duration_ms` and `cost.incremental_usd` for every agent call, and the plan and track calls under `OverheadNode`
(`pipeline/vocabulary.py:53`) with no unit. Two facts about it that this design depends on, both read from `runs/usage-ledger.jsonl`:

- **Its `tier` field is the unit's test kind** (`tier1`, `unit-test`, `e2e-test`, `tier2`; `Unit.tier`, `pipeline/units.py:131`), not
  the review tier. The review tier is `Unit.review_tier` (`:141`), the planner's estimate, and the verdict record
  (`VerdictEntry`, `pipeline/verdict_record.py:27`) keeps `planned_estimate`, `tier` (earned), `final` and `lines` for each unit
  (`verdicts.json` beside the unit store). A forecast by review tier therefore joins ledger rows to units by unit id and reads the
  tier from the verdict record; it never reads `UsageRecord.tier`.
- **The tiers' step usage is not a table anywhere.** Today the verdict "changes nothing the pipeline does" (`review-verdict`), so
  every unit runs the same graph. `units-are-triaged-by-review-tier` makes the tier decide who is interrupted (a card for `light` and
  `full`, none for `auto`), and later changes let an `auto` unit land without a person, so which steps a tier runs will differ
  (an `auto` unit has no round of rework from a person's comments). The forecast must follow that without a table to keep in step.

**The data, re-read** (mean `cost.incremental_usd` of ledger agent rows with a unit): review round 1 $0.97 (308 calls), round 2
$0.50 (185), round 3 $0.39 (23); rework round 0 $0.48, 1 $0.56, 2 $0.31; fix_checks round 1 $0.49, 2 $0.23, 3 $0.20; tests $0.83;
implement $0.55. Of 162 units with a review call, the highest review round was 1 for 24, 2 for 116 and 3 for 22: so 138 (85%)
reached round 2 and 22 of those 138 (16%, 14% of all 162) reached round 3, `max_review_rounds` being 3. Expected review spend per
unit is 0.97 + 0.85 x 0.50 + 0.14 x 0.39, about $1.45, where three full-price rounds are $2.91. The ledger has no review-tier
column, so these are all-tier figures; the per-tier ones are what this change makes the guard compute.

## Decisions

- **The forecast is a sum over recorded cells, not a path model.** A *cell* is a role, node, round and model. For a review tier and
  a unit being forecast:
  `forecast_usd = sum over cells c of reach(c) x mean_cost(c)`, with `reach(c)` the share of the tier's recorded units that ran the
  cell at least once and `mean_cost(c)` the mean incremental cost of the calls in it. Which steps a tier uses is whatever its
  recorded units ran: an `auto` tier with no rework cells has none, a cell the tier never ran is not in the sum, and the day a
  change gives a tier a different route its history says so without an edit here. The conversion to points is the unit's
  `forecast_usd` times each window's `points_per_usd` from `usage-is-estimated-from-recorded-cost`, so the forecast and the estimate
  of what was spent share one scale and nothing converts dollars to a window by assumption. The intercept of that change is not
  added: it is for use the pipeline cannot see.
- **History is units with a final verdict, keyed by the planned tier.** The units counted for a tier are those whose verdict record
  is `final` and whose `planned_estimate` is that tier: the tier a start is judged by is the one the planner gave (`Unit.review_tier`),
  and a unit still running is left out because it has not yet reached the rounds it will reach, which would read as "did not go
  further". A unit with no verdict record (review off, or not yet approved) is in no tier's history. `reach` uses a unit's ledger
  rows under its id; rows of `plan`, `restack` and the rest of `OverheadNode` are not unit cells.
- **Size refines the tier when it can.** The tier's units are split at the median of their `lines` (`VerdictEntry.lines`); a unit
  to be started is in the band its `estimated_lines` falls in. The band is used only when each band has the minimum number of
  units, otherwise the tier's whole history is. Two bands only: a finer split would never have the minimum.
- **A minimum and a prior.** A tier is forecast from its history when it has at least `usage_forecast_min_runs` units (default 10);
  a cell needs that many calls for its own mean, else the cell's mean over every model of that role, node and round is used, and a
  step with fewer than that is the mean of its node. A tier under the minimum, a window with no `points_per_usd` (its basis in force is
  `units`), or a unit with no stored review tier is forecast at the prior: the **flat per-unit allowance of the window**
  (`allowance_for`, `pipeline/usage_allowances.py:150`) as the estimate counts it today. The prior is a number the guard already
  has and the status line says when it is in use; no tier is ever forecast at zero for lack of history.
- **The safety margin is on the rates.** The chance of reaching a later round is the sample rate plus `z(q)` standard errors, capped
  at 1, where `q` is `usage_forecast_quantile` (default 0.9) and the standard error uses the rate smoothed by one success and one
  failure, `(k+1)/(n+2)`, so it is never zero. It is wider for fewer units, tends to the observed rate as units accrue, and at `q` of
  0.5 adds nothing (`z` is 0), which the scenarios use so their arithmetic is exact. The bounds are then made non-increasing in
  the round, because reaching round 3 implies reaching round 2. The step cost is the mean, not a quantile: an upper quantile of
  costs and of rates together would multiply two safety margins and refuse units that fit. The estimate's own margin
  (`usage_headroom_margin_pct`, five points, `config.py:296`) is kept beside this one, for the use the guard cannot see.
- **A unit past its expected rounds is counted at what it spent.** The spent part is in the ledger and in the estimate. The forecast
  of what is **still to come** for a unit that has run `r` rounds of a step is the sum over later rounds `k` of
  `reach(k) / reach(r) x cost(k)`: the chance of the later round *given* the unit got this far. It never subtracts what the unit
  spent beyond the average, never discounts it for being ahead of it, and is 0 past `max_review_rounds` or the last recorded round of
  the cell. A unit at its third review round is forecast at no more review, whatever its tier's average.
- **Where the forecast applies, per ask.**
  - A *start* is a unit's first gate: the unit has no forecast record (below). The forecast is the unit's whole path, every cell,
    plus the plan and track reservations and the running units' remainders.
  - A *later gate* of a unit already admitted is the **asked step only** (the cell the node and round name, at its mean cost, so a
    round 2 review at $0.50 and not the chance-weighted $0.45) plus the same reservations and remainders. That keeps what
    `may_start_unit` says of a running unit ("units already running are not affected", `:1020`): a unit admitted for its whole path
    is not refused its next step because a *later* round of it is unlikely to fit, but a step that does not fit is.
  - A *track's or the planner's* ask forecasts one call at its mean cost, from the `track_*` or `plan` cells of the ledger (the
    cells for them are the same sum with `reach` 1), and is held like a unit.
  - The round-level ask with no unit (`_start_decision`) forecasts the cheapest unit that could start, so a tick is not paused
    while any ready unit would fit: it takes the lowest tier forecast among the startable units, and a start of another is judged
    at its own gate. (A unit that cannot fit is refused there, so the round never starts something the gate would then pause.)
- **A running unit contributes the rest of its current step.** The ledger writes a call when it finishes, so a running step has
  spent points in the reading and not in the ledger, or neither. The gate, on admitting a step, appends a *step* row (unit, node,
  round, time) to the forecast record; a unit whose latest step row has no later ledger row of that unit, node and round is running
  that step, and contributes `cost(cell) x max(1 - elapsed / mean_duration(cell), 0.1)`: the unfinished share of the step's expected
  cost, at least a tenth since a step past its mean duration is still running. The floor and the use of mean duration are
  constants, not settings. A reading taken after the step began already holds part of it, so this counts that part twice; it errs
  towards refusing, and a unit with no step row (killed, or from before this change) contributes nothing, which errs the other way
  and is shown in the status line. Later steps of a running unit are not reserved: each is admitted at its own gate. This is the
  main risk, below.
- **It sits on the cost estimate and does not duplicate it.** `usage-is-estimated-from-recorded-cost` counts what was spent since the
  reading from recorded cost, and a unit admitted on an estimate that has no ledger row yet at the window's flat per-unit allowance
  (`F` in its estimate) because its first call has not ended. This change's remainder of the running step is the better figure for
  the same unit, so it **replaces** that flat allowance for a unit with a step row, and nothing else of the estimate changes. The
  cache file's `estimate_steps` key that change adds (the step a unit was admitted for, estimate admissions only, no time or round)
  is left as it is and not read here: the forecast needs every admitted step with its round and time, on a live reading too, so it
  keeps its own rows (`usage-forecasts.jsonl`), and a rollback of either change loses only its own.
- **Reservations.** A `plan` call is reserved when planning is due (`_needs_planning`, `cli/pipeline.py:1388`), at its mean cost.
  A track is reserved when its systemd timer fires before the window resets: the installed timer's next elapse is read with
  `systemctl --user show` (`abk install-timers`, `docs/cli.md`; the calendars are in `templates/systemd/abk-track-*.timer`), at the
  mean cost of its `track_health`, `track_improve` or `track_recommend` cells plus `track_propose` where propose follows it. A
  track whose timer cannot be read (no systemd, not installed) is not reserved, and the status line says the timers were not read.
  Each window is judged against its own reset time, so a weekly window reserves the week's tracks and the session window only those
  that fire before it resets. A reservation is released when its `plan` or `track_*` row is written.
- **The check and the refusal.** `WindowEstimate` gains the forecast, and `ample` is
  `estimate + forecast + margin < threshold` for each window, so a unit is refused for the window it would overrun. On a live or held
  reading, where no allowance is added, `_decide_start` applies the same check after `may_start_unit` has allowed (so the
  forecast can only make the answer stricter, as the backstops there are) with `spent_pct` 0; this is the one change on the
  non-estimate path and is behind `usage_forecast`. A refusal's reason carries the estimate's text, as now, and then names the
  window, the forecast in points and the **dominant contribution**: the role and node (and round) with the largest points among the
  unit's own cells and the reservations and remainders, for example `unit change/3 (full) forecast 8.6% session: review round 1
  3.1% is the largest; session ~67% estimated + 8.6% forecast is not 5 points under 80%`. A refused unit is stopped as any refusal is
  (`resume_at`, `A refused start stops only that unit`); no new wait cause.
- **Priority 0 and the cap are untouched.** The emergency lane (`emergency_extra`, `emergency_start`, `pipeline/units.py:1149`)
  lifts the slot and worker limits for a priority-0 unit and nothing in `usage_guard.py` reads a priority: a priority-0 unit is held by
  usage like any other, and stays so. The forecast is the same for it, it gets no exemption and no extra, and a unit in the lane that
  is running is a running unit for everyone's forecast. `usage_estimate_max_starts` still counts the units admitted on an estimate for
  a reading and caps them: a start that fits is still refused at the cap, and a start the forecast refuses is not counted.
  A unit admitted is recorded exactly as now (`_record_admitted`); a refusal by the forecast never reaches the cap check.
- **Recorded at admission.** When a unit is admitted the guard appends a forecast row (unit, review tier, band, time, cost and points
  per window, the dollars by role and node, and whether history or the prior was used) to `usage-forecasts.jsonl` in the state
  directory, and a step row for every step admitted. Nothing in the pipeline reads these but the guard (running units) and the report;
  the file is append-only and a line that cannot be parsed is skipped like a half-written ledger line (`read_lines`,
  `usage_ledger.py:337`).
- **Shown.** `abk status` prints, with the usage lines (`_account_usage_lines`, `cli/pipeline.py:642`), a `forecast:` line after the
  estimate: the forecast in points of a unit of each tier for each window with the number of units its history rests on or `prior`,
  the units running with their remaining points, and the reservations. `abk report --by tier` groups by the unit's review tier
  (a new entry in `GROUPINGS`, `pipeline/usage_report.py:46`, with the tier looked up like the report already looks units up
  at `:409`), and shows for each tier the units, the forecast dollars recorded at admission, the actual dollars, their ratio and the
  count of units that spent more than forecast. A unit with no forecast row is counted and shown as unforecast, not as zero.
  The word `tier` here is the review tier; `UsageRecord.tier` stays the test kind and is not what is grouped.
- **Settings** go with the other `usage_*` ones (`config.py:298`): `usage_forecast` (default true), `usage_forecast_min_runs` (10),
  `usage_forecast_quantile` (0.9, above 0 and at most 1). With `usage_forecast: false` no check, row or line is made and the
  decision is what it was. No setting says what a tier's steps are.

## Risks

- **Later steps of a running unit are not reserved**, so several units admitted together can each be fine at their own gate and
  jointly overrun by their later rounds. The cap per reading and the margin bound it for starts on an estimate; on a live reading
  the next reading shows it. A reservation of the units' conditional remainder was rejected as a second forecast of the same
  quantity that the next gate decides with better information.
- **The history is the installation's own and small.** Ten units per tier is a low bar; below it the prior (today's behaviour) is
  used, and the quantile makes ten units read cautiously. A tier whose units are few for a long time stays on the prior, which is
  safe and no better than today. Nothing here is fitted, so there is nothing to overfit.
- **Mean cost per cell is skewed.** One long rework moves a small cell. Cells under the minimum fall back to a wider mean, and the
  report's forecast-against-actual per tier is what shows a bias, to be acted on by a person.
- **A tier's route changing** (the day `auto` units land without a person) makes old history describe the old route for a while.
  Units from before are kept in the history; the report shows the ratio drifting, and `usage_forecast_min_runs` only protects
  the start. Counting only the newest units of a tier was left out until a drift is seen.
- **`Needs:` on two changes that do not exist in this tree yet** (`usage-is-estimated-from-recorded-cost` is being written): the
  names used here (`points_per_usd`, per window, and its replay) are the ones its brief gives.
