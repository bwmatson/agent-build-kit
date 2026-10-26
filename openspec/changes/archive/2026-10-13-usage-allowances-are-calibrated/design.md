# Design

## Motivating measurement

Read-only analysis run on 2026-10-12 over one installation's data. Stated with its limits, because every figure is
small and whole-number.

- `usage-calls.jsonl` held 35 good readings carrying percentages, from 2026-10-10 22:42Z. There were 27 consecutive
  pairs, of which 16 had pipeline spend and no window reset between them (gaps of 1.5 to 2.5 hours, aggregating 1 to
  5 units). The percentages are whole numbers, so a gap's gain carries up to one point of rounding either way.
- **Session window.** Allowance 10 points per spending unit underestimated the real gain in 3 of 16 gaps (worst -7;
  beyond the 5-point margin in 1 of 16, by 2 points). 7 per unit underestimated in 6 of 16 (worst -13). 12 per unit in
  1 of 16 (worst -5). A least-squares fit gave 6.8 points per unit but underestimates too often to serve as the
  allowance.
- **Weekly window.** Real gains were 0 to 2 points per gap (mean about 1). Allowance 2 per unit never underestimated
  but overshot by 4.3 points on average; 1 per unit never underestimated in the 16 gaps (worst 0.0); 0 per unit
  underestimated in 13 of 16; the fit gave 0.37 points per unit.
- **Dollars are not better.** Points per dollar of pipeline spend (session 2.26 per dollar, weekly 0.115) underestimated
  in 10 and 11 of 16 gaps: the person's interactive use of the same account is in the real gains and not in the
  pipeline's dollars. The earlier decision not to derive the allowance from dollars stands.
- **The pause it explains.** At 07:58 on 2026-10-12 the weekly estimate was 72% read plus 5 units at 2 points, about
  82%, against a threshold of 81%. The real weekly figure stayed at 72% all morning (the pipeline being paused) and
  reached 74% six hours later. The installation then set the weekly allowance to 1 by hand.

Limits: one installation, 16 usable gaps, two days of record, gaps of one to five units, no gap without spend
usable as a control, and the interactive use that fills the rest of each gain is not observed at all. The figures show
that a flat 2 was too careful for the week and a flat 10 slightly too loose for the session on this account; they do
not show what another account would measure, which is the argument for measuring each installation and not for a new
constant.

## The calibration

`calibrated_allowances(calls, ledger, *, settings) -> dict[window, Calibrated]` in a new
`pipeline/usage_allowances.py`, a pure function of the two files already on disk, modelled on `calibration(...)` in
`unit_size.py`: ratios from recorded history, a floor, a minimum sample count, a setting to turn it off.

1. **Readings.** The calls of outcome `ok` that carry a percentage for the window (`session_pct` or `weekly_pct`),
   ordered by time. Rows without percentages (older records, cache hits, failures) are ignored.
2. **Pairs.** Each reading is paired with the next reading at least `usage_cache_minutes` later, the pairing
   `most_added` already uses, so two answers taken together are not a gap. A pair is **usable** when: the later figure
   is not below the earlier (a fall is a reset); the gap is no longer than the window's span (five hours for the
   session; seven days for the week) so a reset followed by a climb past the earlier figure is not read as one gain;
   and at least one unit spent in it. A gap with no spend is not a sample: its gain is the person's alone and would
   pull the per-unit figure toward zero.
3. **Units in a gap.** Distinct unit ids on agent rows of the ledger whose time is at or after the earlier reading and
   before the later one, counted by unit id exactly as `units_since` counts for an estimate, so an allowance is
   applied to the same count it was measured against.
4. **Sample.** `gain / units`, in points per unit, for each usable pair; `gain` is the later whole-number figure minus
   the earlier.
5. **Quantile.** The newest `usage_allowance_window` (30) usable pairs, and their `usage_allowance_quantile` (0.9)
   quantile by nearest rank (the ceil(q n)-th smallest). The figure is rounded **up** to a whole number of points:
   the figures read are whole numbers, and rounding down would lower it below what was seen.
6. **Too few.** With fewer than `usage_allowance_min_pairs` (8) usable pairs for the window, no calibration: the
   configured default stands, and the status says how many more are needed.
7. **Bounds at use.** The figure used is `min(max(quantile, floor), ceiling)`. The floor is
   `usage_allowance_floor_pct` per window (default 1 for both: the weekly window must allow for whole-number
   rounding, and a session figure under 1 would make any spend invisible). The ceiling is the configured cap if a whole
   number was set, else twice the built-in default (20 for the session, 4 for the week). The raw quantile is stored, so
   a changed floor, cap or setting takes effect without a recomputation.

### May calibration raise an allowance above the default? Yes, to twice it.

The cost of error is asymmetric. A low allowance admits a start the window cannot take, and that is the harm the guard
exists to prevent; a high one costs a short pause. An account that uses more of its window per unit than the default
assumed should make the guard more careful. The ceiling at twice the default bounds a bad run (a pair set dominated by
heavy interactive use) from silencing the pipeline: the estimate stops being useful long before that.

### The worst case is not a floor.

The brief asks whether the allowance must never fall below the worst gain per unit in the pair window. It does not.
That would let one burst of interactive use fix the allowance at its peak for 30 pairs, which is the false pause again
by another door, and on the measured data the worst session pair (7 points over what 10 per unit gave) would pin the
allowance at the weekly-style extreme. The 90th percentile accepts 1 in 10 misses; what remains is what the margin
(`usage_headroom_margin_pct`) is for, and what the replay command counts, so a person who finds it too loose can raise
the quantile toward 1.0 (which is the worst case) or set the cap. Safety rules, in full: never below the floor; never
above the ceiling; never applied to a window with fewer than the minimum usable pairs; never lowers the margin, the
climb bound or what an actual reading does.

## Where it runs and is kept

- **Computed** once per tick, by the caller that already holds the state directory (`cli/pipeline.py`, with the other
  per-tick usage work), from `usage-calls.jsonl` and the ledger. No model call and no endpoint call. A failure to read
  either file leaves the stored result as it was.
- **Kept** in `usage-allowances.json` beside the cache file, written atomically, one entry per window:
  `{quantile_pct_per_unit, pairs_used, pairs_available, quantile, computed_at}`. Kept apart from the guard's cache
  file: that file is rewritten under a lock on every reading and carries admitted units; a separate file keeps a
  recomputation from contending with it. A file that is missing, unreadable or from a different shape is treated as
  no calibration (defaults), never as an error.
- **Used** by `_estimates` in `usage_guard.py`, which reads the file instead of the setting directly. The pure
  `estimate_usage` is unchanged: it already takes `allowances`.
- **Staleness.** A stored result is used however old, because it is only a summary of history that changes slowly; the
  status shows its age.

## Settings, and telling "set" from "default"

`config.py` fills each window's `usage_unit_allowance_pct` with 10 or 2 in a before-validator when the key is missing,
so the model cannot tell a person's 10 from the default 10. The change makes the value `int | "auto"`, with `auto` the
default when the key is absent and no number filled in. Meaning:

- `auto` (the default): calibrate when `calibrate_usage_allowances` is on; the built-in default (10, 2) is the fallback
  while there are too few pairs; the ceiling is twice it.
- a whole number: the fallback **and** the cap on the calibrated value: calibration may lower it, down to the floor,
  never above it. An installation that set the weekly allowance to 1 keeps exactly 1 (the floor is 1), so no existing
  setting changes behaviour unless it was higher than what the history shows, in which case it is lowered, the intent
  of a cap that was set as an estimate. To pin a value exactly, set the floor equal to it or turn calibration off.
- `calibrate_usage_allowances: false` (the setting turns off, as `calibrate_estimates` does): every window uses its
  number, or its built-in default under `auto`, exactly as before this change.

`usage_unit_allowance_pct: auto` is accepted explicitly so a person can say it. The class-default of 10 for a window
built in code stays the built-in default for `auto`. New settings under `runtimes.claude_code.limits`:
`calibrate_usage_allowances` (true), `usage_allowance_quantile` (0.9, above 0 and not above 1),
`usage_allowance_window` (30, at least 1), `usage_allowance_min_pairs` (8, at least 1, not above the window), and per
window `usage_allowance_floor_pct` (1, at least 0, not above the cap). A bad value fails to load, naming the key.

## What `abk status` prints

With a stored result and calibration on, one line, no call:

`usage allowances: session 9/unit (24 pairs), weekly 1/unit (24 pairs), calibrated`

With too few pairs: `usage allowances: defaults (3 pairs of 8 needed)`, naming per window when they differ
(`session 9/unit (24 pairs), weekly 2/unit default (3 pairs of 8 needed)`). Off: `usage allowances: fixed (calibration
off)`. A figure capped or raised to the floor is marked `(capped)` or `(floor)`. The line is printed where the held
reading is printed.

## The margin stays one value

`usage_headroom_margin_pct` (5) applies to both windows today. The measurement does not support two: the session had 1
miss beyond the margin in 16 gaps (by 2 points), the weekly none. The argument for a separate weekly margin (rounding
of 1 point against bursts in the session) holds in principle, but the data cannot tell a margin of 1 from 5 for the week
because the pause it would prevent was caused by the allowance, not the margin. Left as one value; the replay prints
misses beyond the margin per window, so if a later installation's record shows it, a per-window margin is a small
follow-up with evidence.

## `abk usage replay`

`abk usage replay [--since TIMESTAMP] [--session-allowance N] [--weekly-allowance N] [--margin N]`, in
`cli/usage_cmd.py` beside `backfill-costs`. Read-only: reads `usage-calls.jsonl`, the ledger and the configuration;
makes no model call and no endpoint call; writes nothing, not even the allowances file. `--since` takes an ISO time and
keeps the pairs whose earlier reading is at or after it.

For each window, each usable gap (the definition above, so the table matches what calibration saw), one row:
time, gap, units, read before, actual after, the estimate `before + allowance x units`, and the difference. The
allowance is, by default, the one **calibration would have given at that gap**, computed from the usable pairs before
it only (a walk-forward replay, so the rows are an honest test and not a fit to themselves), the default while there
were too few; `--session-allowance` and `--weekly-allowance` replace it with a fixed number to compare settings, and
`--margin` replaces the margin.

Per window it ends with counts:

- **underestimates**: actual above estimate;
- **misses beyond the margin**: actual above estimate plus margin;
- **false pauses**: estimate plus margin is not below the threshold (the refusal rule) while the actual later reading
  was under the threshold;
- **false allows**: estimate plus margin below the threshold while the actual later reading was at or over it;
- the mean overshoot (estimate minus actual, over gaps it was above), so a person sees the cost of caution.

The threshold is the window's configured `usage_pause_pct`: the call record keeps neither reset times nor the
ramping ceiling, so the replay does not model a threshold that moves toward a reset. It says so in its output.
Output ends with the line the settings would produce today (the `usage allowances:` line) and, with fewer than the
minimum pairs, says there is not enough to judge. Exit 0; with no usable gap it prints that and exits 0.

## Tests and the acceptance opt-out

Everything here is a pure function over two files and a settings object; tier-1 tests with fabricated records prove
each scenario, including the fixture from the measurement (readings and ledger rows constructed to reproduce the
quoted per-gap gains). No acceptance group: a consumer's driven run would need weeks of real history, which a test
cannot fake credibly at the process boundary, and the history files are faked in the tier-1 tests that matter.

## UNVERIFIED

- The 90th percentile, 30 pairs, minimum 8 and floor 1 are recommendations. They are not fitted: the data was 16
  usable gaps. On the measured data, the weekly figure under these rules would be 1 per unit; the session figure was
  not computed and should not be assumed to be the 9 shown as an example in the status line.
- With 16 usable gaps over two days, the minimum of 8 is reached in about a day of pipeline spend on that account; a
  quieter installation may stay on defaults for a week. Not measured elsewhere.
- Whether `at` on a ledger row (the end of the agent call) falls on the right side of a reading for a call that
  straddles it, which would move a unit into the neighbouring gap. The gap lengths (1.5 to 2.5 hours against agent
  calls of minutes) make this a small effect, not a measured one.
- That a fall in the percentage is the only reset signal available: the call record has no reset time. A reset
  followed by a climb past the earlier figure within the window span is excluded only by the span rule. Recording the
  window's reset time on each row would remove the guess; it is a change to the record and left out.
- The replay's use of the static pause percent as the threshold, for the same reason.
- That the weekly window's 7-day span rule matters at all: weekly gaps are hours long.
