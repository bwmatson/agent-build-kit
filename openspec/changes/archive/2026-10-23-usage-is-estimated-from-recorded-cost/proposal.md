## Why

The estimate that lets a start through while the usage endpoint cannot be asked is `reading + allowance x units_since` (`estimate_usage`,
`src/agent_build_kit/pipeline/usage_guard.py:1154-1191`, from `_estimates`, 1204-1238). The allowance is one number per window and per unit, the
0.9 quantile of `gain / distinct units` over the newest 30 pairs of consecutive good readings (`calibrate_pairs`,
`src/agent_build_kit/pipeline/usage_allowances.py:82-98`), clamped to `[1, 2 x built-in]` (`allowance_for`, 150-159). Two things are wrong with it,
and the review tiers will make both worse.

- **A unit is one unit however much it did.** On 2026-10-21 the guard estimated the session at 95% (reading 61%, 54 minutes old, two units x 17)
  when usage was 69%, and paused a unit before its review. One of the two units was only running a review and the other had just begun. The
  ledger knew: every agent call is a row with its role, node, round, model and `cost.incremental_usd` (`UsageRecord`,
  `usage_ledger.py:100-134`). The 17 is a safety quantile, not a fit: over the 95 session pairs of the installation it overestimates by 23 points a
  pair, and its leave-one-out error is 32.9 points against 9.2 for the recorded cost.
- **Spend that belongs to no unit is invisible.** `spend_times` (`usage_ledger.py:352-363`) keeps `(time, unit)` and skips a row with no unit, so
  `plan`, `track_*`, `chat`, `init_*` and `login_refresh` rows never reach the estimate or the pairs. On the installation 6% of the spend in the
  session gaps ($21.86 of $354) is such spend, all of it `plan`.

## What Changes

- **The estimate of a window can be made from the recorded cost.** `spent = points_per_usd x (cost recorded since the reading) + intercept_per_hour
  x (hours since the reading)`, counting every ledger row of the account, with or without a unit, and a row with no cost as zero. A unit admitted on
  an estimate that has no ledger row yet, and a unit whose rows carry no cost, count the window's flat per-unit allowance. The one learned number is
  points per dollar (and the intercept, and a safety scale), kept per window. Cost already carries the model, the role and the longer context of later
  rounds, so no table of per-role or per-round coefficients is fitted: the history cannot identify them and they scored no better than a flat
  model.
- **The rule "not derived from dollars" is replaced.** The size of a window is still not known and no figure converts dollars to a share of a window
  by assumption. The recorded cost is a regressor whose scale, points per dollar, is learned from the pairs of readings, and a window uses it only
  once it has earned that.
- **Calibration fits it and judges it.** `refresh_allowances` (once per tick) also fits, per window with `usage_estimate_basis: cost` (the default),
  a non-negative least-squares line over the newest cost pairs, scales it by the 0.9 quantile of the pairs' own ratio of gain to prediction, and
  adopts it only when a walk-forward over the same gaps shows it no worse than the flat figure on false allows. With too few pairs with cost, no
  adoption, calibration off or `usage_estimate_basis: units`, the flat per-unit estimate applies exactly as today.
- **New settings** beside the `usage_*` ones in `config.py`: per window `usage_estimate_basis` (`cost` | `units`) and `usage_estimate_intercept`
  (on for the session, off for the week); for both windows `usage_cost_min_pairs` (8) and `usage_cost_quantile` (0.9).
- **A versioned stored shape.** `usage-allowances.json` gets `{"version": 2, "windows": {...}}`: the previous reader reads it as `{}` (the
  configured allowances stand) and the new reader reads the previous shape as the flat calibration it was.
- **Shown.** `abk status` says which basis each window is on and why, with points per dollar, the intercept and the pairs behind them; the
  estimate line says how much cost it counted; `abk usage replay` compares flat and cost walk-forward (underestimates, misses beyond the margin, false
  pauses, false allows) and says whether the cost basis would be adopted.
- **Small deltas**: the cap on starts per reading also keeps the step a unit was admitted for (read by the forecast change, unused here), the
  ledger's own-node requirement says an estimate counts a row's cost, and the report's pipeline overhead section shows its share of the cost.
- **Docs**: `docs/configuration.md`, `docs/architecture.md`, `docs/cli.md`, the `abk-config` skill source and the changelog.

Not in this change: the forecast of what a unit about to start will spend (`a-unit-start-forecasts-its-usage-by-tier`), the reading of Claude use
outside abk, and any change to the thresholds, the margin, the climb or the cache rules.
