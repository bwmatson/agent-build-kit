## Context

Code at agent-build-kit `origin/main` (460cad10).

- **The estimate.** `_estimates` (`src/agent_build_kit/pipeline/usage_guard.py:1204-1238`) reads the kept allowances, the ledger of the account
  (`of_account`) and the units admitted on an estimate (`_admitted`, 1199-1201, `estimate_units` in the cache file), then calls `estimate_usage`
  (1154-1191): `read + allowance x units_since`, where `units_since` is `len(admitted | {unit for at, unit in spent if at >= since})`. A reset window
  starts from zero at its reset plus `climb`, the most it could have added (1173-1181). `WindowEstimate` (1125-1151) holds `read_pct`, `spent_pct`
  and renders `session ~15% estimated (0% read + 15% spent)`; `_decide_on_estimate` (1251-1281) refuses unless every window is `estimate + margin <
  threshold`, then caps starts per reading (`usage_estimate_max_starts`) and `_record_admitted` (1284-1297) keeps the unit in the cache under the lock;
  `held_estimate_line` (1300-1314) is the status's copy. The guard knows only the unit (`unit`, `_starting`), not the step.
- **The ledger.** `UsageRecord` (`usage_ledger.py:100-134`) has `unit` (blank for a call outside a unit), `node`, `round`, `role`, `model`, `tier`, `account`,
  `resumed` and `cost: Cost` with `incremental_usd` (absent, never zero, when the call reports none: 78-97). `read_ledger` (347) returns one combined
  record per `(unit, node, round)`: a resumed call adds to the call it resumed, a re-run replaces it, and a node outside `UNIT_CALL_NODES` (56-58)
  stays a record of its own (`grouped_records` 371-400; `combine_records` 279-295 sums `incremental_usd`). `spend_times` (352-363) discards all of that and
  returns `(time, unit)`, skipping a blank unit. Every agent caller writes a row (`plan`, `restack`, `track_*`, `init_*`, `login_refresh`, `chat`,
  `chat_commit`: `usage-accounting`), so the cost of unit-less spend is on disk; a call killed before it delivers a result writes none, and Claude
  use outside abk is not recorded at all.
- **The pairs.** `pairs` (`usage_allowances.py:67-79`) pairs each good reading with the next one at least `usage_cache_minutes` later
  (`consecutive_readings`, `usage_calls.py:266-288`), keeps those with a later figure not lower, a gap within the window's span (`SPANS`: 5 hours,
  7 days) and at least one unit with a record in `[before, after)`; a `UsagePair` is `(at, before, gain, units)` (48-54). `calibrate_pairs` (82-98)
  takes the nearest-rank quantile of `gain / units` over the newest `usage_allowance_window` pairs when there are `usage_allowance_min_pairs`;
  `allowance_for` (150-159) rounds up and clamps it between `usage_allowance_floor_pct` and `allowance_ceiling` (`config.py:312-315`; built-ins
  `BUILTIN_UNIT_ALLOWANCES` session 10, weekly 2, ceiling twice that, `config.py:201`).
- **Kept and shown.** `refresh_allowances` (205-237) runs once per tick (`cli/pipeline.py:1209-1214`, not on a dry run) for the default account and each
  labelled one, and writes `usage-allowances.json` (199-202) as `{window: Calibrated}`; `read_allowances` (188-196) returns `{}` for a file that is
  missing, unreadable or of another shape. `allowances_line` (162-185) renders `usage allowances: session 9/unit (24 pairs), weekly 1/unit (24 pairs),
  calibrated`; `cli/pipeline.py:653-654` prints it with the estimate line under `abk status`. `abk usage replay` (`cli/usage_cmd.py:48-115`) walks the
  pairs, calibrates from the pairs before each, and prints per window the underestimates, misses beyond the margin, false pauses, false allows and
  the mean overshoot, with `--session-allowance`, `--weekly-allowance`, `--margin` and `--since` (118-142).
- **Settings.** `UsageWindowConfig` (`config.py:244-270`, the `session` and `weekly` of `ClaudeLimitsConfig`, 273-324) holds
  `usage_unit_allowance_pct` and `usage_allowance_floor_pct`; the limits hold `calibrate_usage_allowances` (300), `usage_allowance_quantile` (303),
  `usage_allowance_window` (304), `usage_allowance_min_pairs` (305) and `usage_estimate_max_starts` (298).

What the installation's record says (95 session pairs and 105 weekly, measured 2026-10-21 over its own `runs/` files):

- 703 agent rows fall in the session gaps; 6% of the gap spend is unit-less, all `plan`. Gaps are short (median 0.84 hours).
- Leave-one-out RMSE of the points gained, session: the fixed 17 per unit 32.9 (a bias of +23 a pair: it is a safety quantile, not a fit); a flat
  per-unit slope 10.7; a non-negative per-`(role, node)` fit 9.8 to 10.8; the number of agent calls 9.6; **the recorded cost in dollars 9.2, 8.4 with an
  intercept** (about 2.65 points per dollar and about 5 points per gap).
- A first-versus-later-round split is not identifiable: `round` and `resumed` are nearly a function of the node, so per-round coefficients are
  rank-deficient. How often a role ran is still in the data because each pass is a call, and cost carries the later rounds' smaller context.
- Weekly gains are 0, 1 or 2 points (38 of 105 are 0), so every model scores about 0.6 to 0.7: nothing finer than a single figure can be fitted.

## Decisions

- **Cost is a regressor, not a conversion.** The estimate of a window on the `cost` basis is
  `scaled_points_per_usd x C + scaled_intercept_per_hour x H + flat x F`, where `C` is the sum of `cost.incremental_usd` of every ledger row of the
  account at or after the start of the interval (the reading's time, or the window's reset), `H` the hours of the interval, and `F` the number of units
  counted at the flat figure (below). `points_per_usd` and the intercept are learned per window from the pairs; nothing in the code, the settings or
  a price list says how many points a dollar is. This is what the old sentence ("derived from dollars, since the size of a window is not known")
  protected against, and the replacement says so in its place: no dollar-to-window-size assumption, only a scale learned from the readings and
  checked against the flat figure before it is used.
- **A row counts by its cost whether or not it has a unit.** `spend_times` becomes a reader of spend (time, unit or blank, cost) that keeps
  unit-less rows. A row whose `cost.incremental_usd` is absent counts zero: `login_refresh` writes a row with a duration and no cost, and a call killed
  before it delivers writes no row. A unit is still counted once however many rows it has, but only where a unit is the thing counted (the flat
  figure, `F`); cost is summed over rows, and a resumed call is already one record in `read_ledger`, so no call is counted twice. The units basis
  keeps counting units only, so a unit-less row still adds nothing there.
- **Fallbacks to the flat per-unit figure are per piece, not per window.** A unit admitted on an estimate with no ledger row at or after the reading
  (its first call has not ended, so cost is unknown) counts the window's flat allowance. So does a unit with rows at or after the reading none of
  which carries a cost (a runtime that reports none). A unit with some cost counts its cost and nothing more: its running step is not in the ledger
  until the call ends, and estimating it is the forecast's job (`a-unit-start-forecasts-its-usage-by-tier`). The flat figure used is `allowance_for`'s,
  so with the flat calibration absent it is the configured one.
- **A call that ended after the reading counts in full.** The ledger row's time is when the call ended; a call that began before the reading and
  ended after it is counted although part of it was already in the reading. This over-counts a little and keeps the safe side; the pairs are built the
  same way (`before <= at < after`), so the fit has the same bias, and the replay measures it.
- **The intercept is per hour and non-negative.** Use abk does not record (the person's own interactive sessions, a call killed before its row) fills the
  window while the pipeline runs. It is fitted as a per-hour rate, `intercept_per_hour x hours since the reading`, with the fit constrained to be at
  least zero. It is on by default for the session (about 5 points a gap on the data, 8.4 against 9.2 RMSE) and off for the week, whose integer gains of 0
  to 2 points cannot identify a rate. On a window that has reset, the intercept is not added: the climb the estimate already adds from the reset
  (`most_added`) is the allowance for what nobody recorded, and adding both would count it twice.
- **The fit is non-negative least squares over the newest cost pairs.** For two regressors that is the ordinary least-squares solution, or, when a
  coefficient comes out negative, the fit with that coefficient at zero (the intercept first); a points-per-dollar figure not above zero is no fit and
  the window stays flat. A **cost pair** is two consecutive good readings at least `usage_cache_minutes` apart, the later figure not below the earlier,
  a gap within the window's span, with at least one ledger row of the account in the gap (of a unit or not), a recorded cost above zero, and no unit
  that has rows in the gap but none with a cost (such a gap would teach the fit that the unit cost nothing). It differs from the flat pair, which needs a
  unit and ignores cost, so a gap holding only a `plan` call is a cost pair and not a flat pair. The fit uses the newest `usage_allowance_window` (30)
  cost pairs and needs `usage_cost_min_pairs` (8).
- **The safety scale keeps the 0.9 property.** The flat figure is the 0.9 quantile of the samples, so nine gaps in ten were not above it. A least-squares
  line passes through the middle, so it would underestimate half the gaps. The fit is therefore multiplied by `k`, the `usage_cost_quantile` (0.9)
  nearest-rank quantile, over the pairs it was fitted on, of `gain / (the fitted prediction)` for pairs with a prediction above zero, kept between 1 and
  2 (2 is the ceiling the flat allowance has relative to its built-in figure, and a scale above it says the model does not describe the window). The
  kept `points_per_usd` and `intercept_per_hour` already include `k` and are rounded up to 0.01, so the estimate is a multiplication and an addition and the
  scale is shown, not applied twice. There is no per-unit floor or ceiling on this basis: the safeguards are the non-negative fit, the clamp on `k`,
  the adoption guard and the margin.
- **Adoption: no worse than flat on false allows, decided from the same files.** The default `usage_estimate_basis` is `cost`, and a window is
  estimated from cost only when its kept calibration says so. After fitting, the tick judges the cost basis walk-forward over the newest `usage_allowance_window`
  cost pairs: for each pair after the first `usage_cost_min_pairs`, the fit from the pairs before it and the flat allowance calibrated from the flat pairs
  before it each estimate the gap from the earlier reading (the cost estimate from the cost and hours of the gap; the flat one from the units of the gap,
  zero for a gap with none), against the window's configured `usage_pause_pct` and the `usage_headroom_margin_pct` (the replay's static threshold). A *false
  allow* is an estimate plus the margin under the threshold while the next reading was at or above it. The cost basis is adopted when at least
  `usage_cost_min_pairs` gaps were judged (so the first adoption needs twice the pairs a fit does) and its false allows are not more than the flat
  figure's. Underestimates and false pauses are shown, not gated: the data shows the flat figure's weakness is a large overestimate (false pauses), and
  adopting only on false allows keeps the one safety property that matters and lets the cheaper-in-lost-work change through. The result and the reason
  (`too_few_pairs`, `too_few_judged`, `more_false_allows`, `no_fit`, `basis_units`) are kept with the figures.
- **Default `cost`, not `units`, and why.** Shipping `units` first with the replay would leave the 2026-10-21 failure in place until someone flips a
  setting, and the guard that flips it automatically is the adoption rule above: a window moves to cost only when the recorded history shows it no
  worse on false allows. The default is therefore safe on any installation (too few pairs, too little history or a runtime that reports no cost stay
  flat, as today) and is fast to prove right on this one (95 session pairs: well above 16). `units` stays as the per-window opt-out, and
  `calibrate_usage_allowances: false` turns all of it off with today's estimate exactly.
- **The weekly window is fitted as one per-cost figure, no intercept, and judged like the session.** Gains of 0, 1 or 2 points cannot identify a
  per-unit or a per-role figure, so the cost basis fits only a points-per-dollar slope through the origin (the intercept setting defaults to off for the
  week) and the units basis stays as it is. Nothing assumes it will be adopted: with integer-rounded gains most weekly gaps are zeros and the adoption
  guard decides on the data, whichever way it falls. The weekly estimate is a fraction of a point per dollar, so `spent_pct` is a float, as it already is.
- **The stored file is versioned and neither reader fails.** The new shape is `{"version": 2, "windows": {"session": {...}, "weekly": {...}}}`, each
  window holding the previous `Calibrated` fields (quantile, pairs used and available, the flat figure, the time) and the basis in force, the reason
  for it, `points_per_usd`, `intercept_per_hour`, `safety_scale`, the cost pairs held and judged, and the false allows of each model. The previous
  reader iterates the top level and fails validation on `"version"`, so it reads the new file as `{}` and the configured allowances stand (a
  rollback loses calibration for a tick, not safety). The new reader reads a top level of `Calibrated` objects (the previous shape) as the flat
  calibration it was, with the basis `units` and the reason `previous file`, and reads an unknown `version` as `{}`; the next tick rewrites the
  file whole (`write_allowances`, atomic).
- **The decision reads the file, not the record.** As today (`usage-pause`: an estimate reads the file and does not recompute), only the ledger rows
  since the reading are read at decision time, for their cost. `_estimates` reads the kept result, the account's ledger and the admitted units, and
  nothing is fitted there.
- **`estimate_usage` takes the spend, not a unit count.** The decision of how many points were spent since a time becomes a function of the window and
  the time (cost, hours, units counted at the flat figure), so that the flat and the cost basis are two implementations behind one call and the
  climb/reset logic does not change. The units basis returns exactly the figure `allowance x units_since` gave, which the existing tests keep
  asserting unchanged.
- **The cap records the step.** `_record_admitted` also keeps, beside the unit, the step it was admitted to start (when the caller passes one) under a
  new key of the cache file (`estimate_steps`), not by changing `estimate_units`, so the previous reader keeps reading the list of units and a
  rollback loses only the steps. Nothing in this change reads it; the forecast does.
- **The report names what the estimate counts.** The `pipeline overhead` section of the report is what the cost basis now adds to the estimate; it states
  its cost and share of the ledger's total so a person can see how much that is. No new report or view.
- **Status and replay show both.** `abk status` prints the basis in force per window and why (points per dollar, intercept, scale, pairs), and the
  estimate line says how much recorded cost it counted. `abk usage replay` keeps its rows and its all-gaps flat counts as they are and, per window,
  adds a flat line and a cost line over the same gaps (those after the first `usage_cost_min_pairs` cost pairs) and the adoption verdict. The cost
  figures in the replay are fitted walk-forward from the pairs before each gap, as the flat allowance already is.

## How the forecast reuses this

`a-unit-start-forecasts-its-usage-by-tier` forecasts the cost in dollars of a unit about to start from the observed mean cost per `(role, node, round,
model)` and converts it with the window's **`points_per_usd`** and, for hours of waiting, the **intercept**, both as kept in `usage-allowances.json` by
this change (version 2, per window, with the basis and the reason it is or is not adopted: the forecast uses a window's scale only where it is
adopted and falls back to its flat per-unit prior elsewhere). The **per-step observed cost** is the ledger reader this change makes, which returns
cost keyed by time, unit, node and round for rows with or without a unit; the forecast sums it by `(node, round, model)` rather than by time. The
step a unit was admitted for is the `estimate_steps` key written here. This change decides nothing about tiers, passes per role or reservation, and
adds no forecast to the estimate.

## Risks

- **A cost basis that is wrong in a way the walk-forward cannot see**, such as a change of model mix after the pairs it was fitted on. The fit is the
  newest 30 pairs, recomputed every tick, the safety scale is a quantile of its own misses, and the 0.9 property is measured by the replay; the adoption
  guard keeps flat where cost is worse. A window that stops being adopted shows the reason in `abk status`.
- **Unrecorded use** (an interactive session in the same window) is a per-hour intercept on the session and nothing on the week; the margin
  (`usage_headroom_margin_pct`) and the threshold are unchanged and remain the guard against it.
- **A larger unit-less share later** (tracks and chat run more) is counted at its cost from the first row, which is the point of counting it.
- **Over-counting a call that straddles the reading** is the safe direction and is built into the pairs as well.

## Needs

No `Needs:`. It builds on `usage-accounting`'s recording of every agent caller, which is merged.

## Not in this change

- The forecast of what a unit about to start will spend, by review tier and by passes per role, the remaining expected cost of running units, the
  reservation for plan calls and due tracks, and refusal reasons naming the dominant role: `a-unit-start-forecasts-its-usage-by-tier` (it needs
  `units-are-triaged-by-review-tier` and this change).
- A per-`(role, node, round)` table of coefficients (the history cannot identify it).
- Reading Claude use outside abk, other than as a per-hour intercept.
- Changing a threshold, the headroom margin, the climb floor, the cache times or what refuses a start.
- Per-role cost by tier in `abk report`.
