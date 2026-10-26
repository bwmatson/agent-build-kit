## MODIFIED Requirements

### Requirement: The estimate adds what the pipeline may have spent since the reading

The estimate of a window SHALL be the reading's figure for that window plus, for each unit that has spent since the reading or been
admitted on an estimate since the reading, an allowance of points for that window: the calibrated allowance of the window when it has
one, and otherwise the configured one (`usage_unit_allowance_pct` on each window's settings, ten points for the session window and two for the weekly by default). A unit
spends since the reading when the usage ledger holds a record of it at or after the time the reading was fetched; a unit is
counted once however many records it has. The allowance SHALL NOT be derived from dollars, since the size of a window is not known.

#### Scenario: Units that spent since the reading

- **GIVEN** a kept reading with the session at 70% against 92%, an allowance of ten points, a margin of five and ledger records for one unit since the reading
- **WHEN** a unit asks to start with the read refused
- **THEN** the estimate is 80%, and the start is allowed because 80 plus 5 is below 92

#### Scenario: Estimated spend pushes it past the threshold

- **GIVEN** the same reading and ledger records for two units since it
- **WHEN** a unit asks to start with the read refused
- **THEN** the estimate is 90%, and the start is refused because 90 plus 5 is not below 92

#### Scenario: One unit with many records

- **GIVEN** ledger records of one unit at four different times since the reading
- **WHEN** the estimate is made
- **THEN** that unit counts once

#### Scenario: A unit admitted on an estimate that has not yet recorded

- **GIVEN** a unit admitted on an estimate whose agent call has not ended, so it has no ledger record
- **WHEN** the next unit asks to start
- **THEN** the admitted unit is counted, and it is counted once when its record arrives

#### Scenario: Settings

- **WHEN** an allowance is below zero or a margin is below zero
- **THEN** the configuration is refused

#### Scenario: A calibrated allowance is the one applied

- **GIVEN** a kept reading with the weekly at 70%, a calibrated weekly allowance of one point and ledger records for three units since the reading
- **WHEN** a unit asks to start with the read refused
- **THEN** the weekly estimate is 73%, not the 76% the configured two points would give

## ADDED Requirements

### Requirement: The allowance of a window is calibrated from the usage the installation has recorded

When `calibrate_usage_allowances` is on (the default), the framework SHALL derive each window's allowance from the recorded good
readings and the ledger, from files on disk and without a model call or a call to the usage endpoint. A pair is two consecutive good
readings of a window at least `usage_cache_minutes` apart, with the later figure not below the earlier, a gap no longer than the
window's span, and at least one unit that spent in it. Its sample is the points gained divided by the number of distinct units whose
agent records fall in the gap, counted by unit id as an estimate counts them. The allowance SHALL be the `usage_allowance_quantile`
(0.9 by default) of the samples of the newest `usage_allowance_window` (30) pairs, rounded up to a whole number of points, kept
between the window's `usage_allowance_floor_pct` (1) and its ceiling, and SHALL apply only when the window has at least
`usage_allowance_min_pairs` (8) pairs; otherwise the configured allowance stands. The ceiling is the whole number set as
`usage_unit_allowance_pct`, or twice the built-in default when it is `auto` (the default), so calibration may raise an allowance above its default but never above its ceiling.
With the setting off, every window uses its configured allowance.

#### Scenario: A weekly window that gains little

- **GIVEN** twelve usable weekly pairs whose gains per unit are 0, 0, 0.5, 0.5, 0.5, 1, 1, 0.5, 0, 1, 0.5 and 2, a floor of one, a minimum of eight and the default quantile
- **WHEN** the allowances are calibrated
- **THEN** the weekly allowance is 1 point per unit, not the default 2

#### Scenario: A session window that costs more than the default

- **GIVEN** ten usable session pairs whose gains per unit are all between 11 and 14 points and the default of 10 with a ceiling of 20
- **WHEN** the allowances are calibrated
- **THEN** the session allowance is above 10 and not above 20

#### Scenario: Too few pairs

- **GIVEN** seven usable pairs for a window and a minimum of eight
- **WHEN** the allowances are calibrated
- **THEN** the window's configured allowance stands and nothing calibrated is applied

#### Scenario: A gap that is not a sample

- **GIVEN** readings whose gap holds no unit that spent, readings whose later figure is lower, readings less than `usage_cache_minutes` apart, and a gap longer than the window's span
- **WHEN** the pairs are made
- **THEN** none of them is a usable pair

#### Scenario: The floor and the ceiling

- **GIVEN** a quantile of 0 points per unit with a floor of one, and another of 40 with a ceiling of 20
- **WHEN** the allowances are applied
- **THEN** the first is 1 and the second is 20

#### Scenario: An explicit allowance is a cap

- **GIVEN** `usage_unit_allowance_pct: 3` for the weekly window and a calibrated quantile of 5
- **WHEN** the allowance is applied
- **THEN** it is 3, and a quantile of 1 gives 1

#### Scenario: Calibration off

- **GIVEN** `calibrate_usage_allowances: false` and a record that would calibrate both windows
- **WHEN** an estimate is made
- **THEN** each window uses its configured allowance, as before this change

#### Scenario: Settings

- **WHEN** the quantile is not above 0 or is above 1, a window or minimum is below 1, the minimum is above the window, a floor is negative or above the cap, or an allowance is neither a whole number nor `auto`
- **THEN** the configuration is refused naming the key

### Requirement: The calibrated allowances are computed once a tick and kept with their inputs

The framework SHALL compute the allowances at most once in a tick and keep the result, per window with the quantile, the pairs used,
the pairs available and the time, in a state file beside the guard's cache file. An estimate SHALL read that file and not recompute
from the record. A file that is missing, unreadable or of another shape SHALL mean no calibration, not an error. The status command
SHALL print, without a call, one line of the allowances in force and the pairs behind them, or that the defaults stand and how many pairs are needed, or that calibration is off.

#### Scenario: The status line

- **GIVEN** a kept result of 9 points for the session on 24 pairs and 1 for the weekly on 24 pairs
- **WHEN** the status command is run
- **THEN** it prints `usage allowances: session 9/unit (24 pairs), weekly 1/unit (24 pairs), calibrated` and makes no call

#### Scenario: Defaults stand

- **GIVEN** a window with three usable pairs and a minimum of eight
- **WHEN** the status command is run
- **THEN** the line says the defaults stand and that three pairs of eight are held

#### Scenario: A damaged file

- **GIVEN** a state file that cannot be read
- **WHEN** an estimate is made
- **THEN** the configured allowances are used and the tick does not fail

#### Scenario: Computed once

- **GIVEN** a tick in which two units ask to start
- **WHEN** both are decided
- **THEN** the record is read for the allowances once

### Requirement: The usage replay re-runs the estimator over the recorded history

`abk usage replay` SHALL re-run the estimate over the recorded readings and ledger without a model call, a call to the usage
endpoint or a write, and print for each window and each usable gap (optionally from `--since`) the reading before, the reading after, the units, and the estimate made from the first, and per window the counts of underestimates, of actual readings beyond the estimate plus the margin, of false pauses (an estimate refused by the headroom rule while the next actual reading was under the threshold) and of false allows. The allowance replayed
SHALL be the one calibration would have given from the pairs before each gap, unless `--session-allowance` or `--weekly-allowance` fixes
one, and `--margin` SHALL replace the margin; the threshold SHALL be the window's configured pause percent, and the output SHALL say so.

#### Scenario: Counts over a record

- **GIVEN** a record of five usable weekly gaps, one with an actual reading above the estimate and two with an estimate refused while the actual was under the threshold
- **WHEN** `abk usage replay` is run
- **THEN** the weekly counts are one underestimate and two false pauses

#### Scenario: Walk-forward allowance

- **GIVEN** a record of twelve usable gaps and a minimum of eight
- **WHEN** it is replayed
- **THEN** the first eight gaps use the configured allowance and the later ones the allowance calibrated from the gaps before each

#### Scenario: Trial settings

- **GIVEN** the same record and `--weekly-allowance 1 --margin 3`
- **WHEN** it is replayed
- **THEN** every weekly gap uses one point and a margin of three

#### Scenario: Read-only

- **WHEN** it is run
- **THEN** no file is written and no call is made, and with no usable gap it prints that and exits 0

#### Scenario: Since

- **GIVEN** a record spanning three days and `--since` at the start of the third
- **WHEN** it is replayed
- **THEN** only gaps whose first reading is at or after it are shown
