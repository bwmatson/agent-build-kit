# Proposal

## Why

When the usage endpoint cannot be asked, the guard estimates each window as the last good reading plus a flat
allowance of points for every unit that has spent since (`usage_unit_allowance_pct`: 10 for the session, 2 for the
week). The numbers are guesses, and one of them paused a pipeline that had room. The measurement is in the design:
over the recorded readings of one installation the weekly window gained 0 to 2 points per gap (mean about 1) while
the flat allowance charged 2 per unit, an average overshoot of 4.3 points; the session allowance of 10 was too low
in 3 of 16 gaps. The estimate that paused the pipeline read 72% plus 5 units at 2 points against a threshold of
81% while the real figure stayed at 72% for six hours. The record that would have corrected it, every good reading
with its percentages beside the ledger of what the pipeline spent, is already on disk.

## What Changes

- **The allowance of each window is calibrated.** From pairs of consecutive good readings in the same window, with
  the units that spent between them, the allowance becomes a high quantile (the 90th by default) of points gained
  per unit over the recent pairs, never below a floor, never above a ceiling, and only with a minimum number of
  pairs; otherwise the configured default stands. It can rise above the default, to twice it, because a heavier
  account must make the guard more careful, never less.
- **It is computed from files on disk**, once a tick, with no model call and no endpoint call, and stored with its
  inputs (pairs used, quantile, when) so a person can see where a figure came from.
- **`abk status` says which allowances are in force** and how many pairs back them, or that defaults stand and how
  many pairs are still needed.
- **Settings:** `calibrate_usage_allowances` (on by default); `usage_unit_allowance_pct` takes a whole number or
  `auto` (the default), a number being a cap on the calibrated figure and the fallback; the quantile, the pair
  window, the minimum and the floor are settings.
- **`abk usage replay [--since TIMESTAMP]`** re-runs the estimator over the recorded readings and ledger and prints,
  per usable gap, the estimate against the actual reading, with the counts of underestimates, misses beyond the
  margin and false pauses, and accepts trial settings, so the by-hand analysis behind this change is a command.
- **Not included:** a per-window margin (the design records why it is left out), a dollar-based allowance (the
  measurement shows it is no better), any change to the climb bound, and any change to what an actual reading does.

## Impact

- agent-build-kit: `pipeline/usage_guard.py`, a new `pipeline/usage_allowances.py`, `config.py`, `cli/usage_cmd.py`,
  the status command, `docs/configuration.md`, `docs/cli.md`, `docs/architecture.md`, the `abk-config` skill and the
  changelog.
- Specs: `usage-pause` modifies one requirement and adds three.
