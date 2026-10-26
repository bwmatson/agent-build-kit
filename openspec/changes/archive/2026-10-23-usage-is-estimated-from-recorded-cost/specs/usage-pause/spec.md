## MODIFIED Requirements

### Requirement: The estimate adds what the pipeline may have spent since the reading

The estimate of a window SHALL be the reading's figure for that window plus what the pipeline may have spent in it since the reading, worked out
on the window's estimate basis, `units` or `cost` (`usage_estimate_basis` on each window's settings, `cost` by default). The basis of a window is
the one its kept calibration says is in force: `cost` only when the calibration holds a cost fit that has been adopted for that window, and `units`
in every other case (the setting is `units`, calibration is off, the calibration is missing or unreadable, too few pairs hold a cost, or the cost
fit was not adopted). Each window is worked out on its own basis.

On the `units` basis, the spend SHALL be an allowance of points for that window for each unit that has spent since the reading or been admitted on an
estimate since the reading: the calibrated allowance of the window when it has one, and otherwise the configured one (`usage_unit_allowance_pct`
on each window's settings, ten points for the session window and two for the weekly by default). A unit spends since the reading when the usage
ledger holds a record of it at or after the time the reading was fetched; a unit is counted once however many records it has; a record with no unit
adds nothing.

On the `cost` basis, the spend SHALL be `points_per_usd x C + intercept_per_hour x H + flat x F`, where `points_per_usd` and `intercept_per_hour` are
the window's kept figures (each already including its safety scale; the intercept is zero when the window's `usage_estimate_intercept` is off);
`C` is the sum of the recorded incremental cost, in dollars, of every ledger record of the account at or after the time the reading was fetched, with
a unit or without one (the planner, a track, a chat turn, the conflict resolver and init's runs included), a record with no cost counting zero; `H`
is the hours since the reading; and `flat` is the window's flat per-unit allowance as on the `units` basis, applied to `F`, the number of units that
were admitted on an estimate since the reading and have no ledger record at or after it, plus the number of units that have records at or after it
none of which carries a cost. A unit that has a record with a cost counts its cost and nothing more.

No figure converts dollars into a share of a window by assumption, because the size of a window is not known. The recorded cost is a regressor
whose scale, points per dollar, is learned from the installation's own pairs of readings, and nothing built in, configured or taken from a price list
supplies it. A window with no learned and adopted scale is estimated on the `units` basis.

#### Scenario: Units that spent since the reading

- **GIVEN** a kept reading with the session at 70% against 92%, the session window on the `units` basis with an allowance of ten points, a margin of five and ledger records for one unit since the reading
- **WHEN** a unit asks to start with the read refused
- **THEN** the estimate is 80%, and the start is allowed because 80 plus 5 is below 92

#### Scenario: Estimated spend pushes it past the threshold

- **GIVEN** the same reading and ledger records for two units since it
- **WHEN** a unit asks to start with the read refused
- **THEN** the estimate is 90%, and the start is refused because 90 plus 5 is not below 92

#### Scenario: One unit with many records

- **GIVEN** the window on the `units` basis and ledger records of one unit at four different times since the reading
- **WHEN** the estimate is made
- **THEN** that unit counts once

#### Scenario: A unit admitted on an estimate that has not yet recorded

- **GIVEN** a unit admitted on an estimate whose agent call has not ended, so it has no ledger record
- **WHEN** the next unit asks to start, on either basis
- **THEN** the admitted unit is counted at the window's flat allowance, and once its record arrives it is counted by its record, on the `cost` basis by its cost and on the `units` basis once

#### Scenario: Settings

- **WHEN** an allowance is below zero or a margin is below zero
- **THEN** the configuration is refused

#### Scenario: A calibrated allowance is the one applied

- **GIVEN** a kept reading with the weekly at 70%, the weekly window on the `units` basis with a calibrated weekly allowance of one point and ledger records for three units since the reading
- **WHEN** a unit asks to start with the read refused
- **THEN** the weekly estimate is 73%, not the 76% the configured two points would give

#### Scenario: The 2026-10-21 case

- **GIVEN** a kept reading 54 minutes old with the session at 61% against a threshold of 80%, a margin of five, a session cost fit of 2.65 points per dollar and an intercept of 5 points an hour, a flat allowance of 17 points, and since the reading ledger records for two units, one a `review` call of $0.97 and the other a `rework` call of $0.48
- **WHEN** a unit asks to start with the read refused
- **THEN** the session estimate is about 69% (61 read plus 3.84 for the $1.45 recorded plus 4.5 for 0.9 hours), not the 95% two flat allowances of 17 gave, and the start is allowed because 69 plus 5 is below 80

#### Scenario: A unit with three review rounds costs more than one with one

- **GIVEN** a session window on the `cost` basis at 2.65 points per dollar with no intercept, a reading of 70%, and since it either one unit with `review` records of $0.97, $0.50 and $0.39 for three rounds, or one unit with a single `review` record of $0.97
- **WHEN** the estimate is made for each
- **THEN** the first adds 4.93 points and the second 2.57, and on the `units` basis both add the same flat figure

#### Scenario: Spend with no unit is counted by its cost

- **GIVEN** the session window on the `cost` basis at 2.65 points per dollar with no intercept, a reading of 60%, no unit that has spent and a `plan` record with no unit of $2.10 since the reading
- **WHEN** the estimate is made
- **THEN** it is 65.6%, and on the `units` basis the same record adds nothing

#### Scenario: A record with no cost counts zero

- **GIVEN** the `cost` basis, a `login_refresh` record with no cost and a duration since the reading, and no other record
- **WHEN** the estimate is made
- **THEN** the record adds nothing to the recorded cost and no unit is counted for it, and a call killed before it delivered a result, which wrote no record, adds nothing either

#### Scenario: A unit whose records carry no cost counts the flat allowance

- **GIVEN** the `cost` basis, a unit with two records since the reading, neither with a cost, and another unit with a record of $0.50
- **WHEN** the estimate is made
- **THEN** the first unit counts the window's flat allowance, the second counts its $0.50 at the window's points per dollar, and neither counts twice

#### Scenario: Cost before the reading is not counted

- **GIVEN** the `cost` basis, a record of $3.00 one minute before the reading was fetched and a record of $1.00 at the time it was fetched
- **WHEN** the estimate is made
- **THEN** only the $1.00 is counted

#### Scenario: A record of another account is not counted

- **GIVEN** the `cost` basis, a labelled account whose reading is estimated and records of $2.00 that carry another account's key
- **WHEN** the estimate is made for the labelled account
- **THEN** those records add nothing, as for units

#### Scenario: Calibration off keeps the flat estimate exactly

- **GIVEN** `calibrate_usage_allowances: false`, a unit-less `plan` record and a kept cost fit left in the file by an earlier run
- **WHEN** an estimate is made
- **THEN** each window is on the `units` basis with its configured allowance, the estimate is the figure it was before this change and the `plan` record adds nothing

#### Scenario: Too few pairs with cost

- **GIVEN** seven cost pairs for a window and `usage_cost_min_pairs` of eight
- **WHEN** an estimate is made
- **THEN** the window is on the `units` basis and the estimate is the flat one

#### Scenario: A window is on its own basis

- **GIVEN** a session window with an adopted cost fit and a weekly window whose cost fit was not adopted
- **WHEN** an estimate is made
- **THEN** the session estimate is made from cost and the weekly one from the units that spent, in the same reason line

### Requirement: A window that has reset since the reading is estimated from its reset

A window whose reset time lies between the reading's time and now SHALL NOT take the reading's figure. Its estimate SHALL start at
zero at the reset, add the most that could have been added since the reset (the fastest climb seen for that window, no slower than
the configured floor, with its margin), and add what the pipeline spent since the reset on the window's basis: on the `units` basis the allowance for
each unit that has spent or been admitted since the reset, and on the `cost` basis the window's points per dollar times the recorded cost of every
ledger record at or after the reset, with or without a unit, plus the flat allowance for each unit admitted since the reset with no record at or
after it and each unit with records at or after it none carrying a cost. On the `cost` basis the per-hour intercept is not added after a reset: the
climb is the allowance for what nobody recorded. A window the reading says is not open SHALL start from its figure, which is zero.

#### Scenario: The session window has reset

- **GIVEN** a kept reading from before the session window's reset, with the session at 88%, the reset forty minutes ago and the weekly window not reset
- **WHEN** a unit asks to start with the read refused
- **THEN** the session estimate starts from the reset, not from 88%, and the weekly estimate from its reading

#### Scenario: The reset was long ago

- **GIVEN** a session window that reset ten hours ago, a climb floor of 0.2 points a minute and a margin of 2
- **WHEN** the session estimate is made
- **THEN** it is 122 points and the start is refused for the session, since no estimate could be trusted that far from a reading

#### Scenario: A reset window on the cost basis

- **GIVEN** a session window on the `cost` basis at 2 points per dollar with an intercept of 5 points an hour, a climb from the reset of 6 points, $1.00 recorded after the reset and $4.00 recorded before it, the reading older than the reset
- **WHEN** the session estimate is made
- **THEN** it is 8 points (6 climb plus 2 for the $1.00 after the reset), and the $4.00 before the reset and the intercept add nothing

### Requirement: Starts on an estimate are capped per reading

The guard SHALL admit at most `usage_estimate_max_starts` units (three by default) on an estimate for one reading; the count SHALL be
kept with the reading in the cache and start again from zero when a good reading is taken. A start refused by the cap
SHALL be refused until the next permitted call, with a reason that says the cap was reached. When the caller names the step the start is for, the
guard SHALL keep that step with the unit it admits, under a key of its own beside the list of units, so that a reader that knows only the list of
units reads the same list as before. The cap counts units, not steps.

#### Scenario: The cap is reached

- **GIVEN** a cap of three, a kept reading with ample headroom and three units admitted on an estimate since it
- **WHEN** a fourth unit asks to start with the read refused
- **THEN** it is refused until the time the endpoint may next be asked, and the reason says three starts have been made on an estimate

#### Scenario: A good reading resets the count

- **GIVEN** three units admitted on an estimate and then a good live reading
- **WHEN** a unit asks to start
- **THEN** it is decided from the new reading, and the count is zero

#### Scenario: The step is kept with the unit

- **GIVEN** a unit admitted on an estimate for the step `review`
- **WHEN** the cache file is read
- **THEN** the list of admitted units holds the unit exactly as before, the steps hold `review` for it, and a second admission of the same unit does not count it twice

#### Scenario: No step named

- **WHEN** a unit is admitted and the caller names no step
- **THEN** the unit is kept as before and no step is kept for it

### Requirement: A start on an estimate says so

A decision to start on an estimate SHALL carry a reason that gives the reading's age, each window's estimate with the figure read and the
points added, and that starts are being allowed, for example `usage: reading 89m old, session ~15% estimated (0% read + 15% spent),
weekly ~71% estimated (65% read + 6% spent), allowing starts`. A window estimated from recorded cost SHALL also say how much cost was counted,
`~69% estimated (61% read + 8% spent from $1.45 recorded)`, and, when units were counted at the flat allowance because they had no record or no
cost yet, how many (`, 1 unit not yet recorded` or `, 2 units not yet recorded`) inside the same parentheses; a window on the `units` basis keeps
the previous wording. A refusal that rests on an estimate SHALL say so in the same terms. The
status command SHALL print the same line, without a call, whenever the reading it holds is older than the time a reading is kept and
the endpoint cannot be asked.

#### Scenario: The reason of an allowance

- **WHEN** a start is allowed on an estimate
- **THEN** the reason shows the reading's age, the estimate of each window with the figure read and the points added, and the threshold each is judged against

#### Scenario: The reason of a cost estimate

- **GIVEN** a session estimate made from $1.45 recorded and a weekly estimate on the `units` basis
- **WHEN** a start is allowed on the estimate
- **THEN** the session part reads `session ~69% estimated (61% read + 8% spent from $1.45 recorded) under 80%` and the weekly part reads as it did before this change

#### Scenario: Units not yet recorded

- **GIVEN** a cost estimate that counted one admitted unit at the flat allowance
- **WHEN** the reason is written
- **THEN** it says `1 unit not yet recorded` beside the recorded cost

#### Scenario: The status command

- **GIVEN** a held reading older than the time a reading is kept and a cool-down in force
- **WHEN** the status command is run
- **THEN** it prints the estimate line, makes no call, and still prints the held reading and its age

### Requirement: The allowance of a window is calibrated from the usage the installation has recorded

When `calibrate_usage_allowances` is on (the default), the framework SHALL derive from the recorded good readings and the ledger, from files on
disk and without a model call or a call to the usage endpoint, two things for each window: the flat per-unit allowance, and, when the window's
`usage_estimate_basis` is `cost` (the default), a cost fit that is adopted only when it has earned it. With the setting off, every window uses its
configured allowance, on the `units` basis, and nothing is fitted.

The flat allowance: a pair is two consecutive good readings of a window at least `usage_cache_minutes` apart, with the later figure not below the
earlier, a gap no longer than the window's span, and at least one unit that spent in it. Its sample is the points gained divided by the number of
distinct units whose agent records fall in the gap, counted by unit id as an estimate counts them. The allowance SHALL be the `usage_allowance_quantile`
(0.9 by default) of the samples of the newest `usage_allowance_window` (30) pairs, rounded up to a whole number of points, kept
between the window's `usage_allowance_floor_pct` (1) and its ceiling, and SHALL apply only when the window has at least
`usage_allowance_min_pairs` (8) pairs; otherwise the configured allowance stands. The ceiling is the whole number set as
`usage_unit_allowance_pct`, or twice the built-in default when it is `auto` (the default), so calibration may raise an allowance above its default but never above its ceiling.

The cost fit: a cost pair is two consecutive good readings at least `usage_cache_minutes` apart, the later figure not below the earlier, a gap no
longer than the window's span, with at least one ledger record of the account in the gap (of a unit or of none), a recorded cost above zero in it, and
no unit that has records in the gap and none with a cost. Its regressors are the gap's recorded incremental cost in dollars, `C`, and its length in
hours, `H`; its response is the points gained. Over the newest `usage_allowance_window` cost pairs, and only when there are at least
`usage_cost_min_pairs` (8) of them, the fit SHALL be the non-negative least-squares line of gain on `C` (and on `H` when the window's
`usage_estimate_intercept` is on; on by default for the session and off for the weekly), which is the ordinary least-squares solution or, when a
coefficient is negative, the fit with it at zero; a points-per-dollar figure not above zero is no fit. The safety scale SHALL be the
`usage_cost_quantile` (0.9 by default) nearest-rank quantile, over the pairs fitted, of the gain divided by the fitted prediction for the pairs whose
prediction is above zero, kept between 1 and 2. The kept points per dollar and intercept per hour SHALL be the fit times the scale, rounded up to
0.01. The window's weekly fit is a single figure of points per dollar, because its gains are whole points of 0, 1 or 2 and nothing finer is
identifiable.

Adoption: after fitting, the framework SHALL judge the cost fit walk-forward over the newest `usage_allowance_window` cost pairs. For each cost
pair after the first `usage_cost_min_pairs`, it SHALL estimate the gap from the earlier reading twice: from the cost fit made from the cost pairs
before it, and from the flat allowance calibrated from the flat pairs before it (the configured one while there were too few) counted for the units
in the gap, none for a gap with no unit; each estimate SHALL be judged against the window's configured `usage_pause_pct` with the headroom margin.
A false allow is an estimate whose figure plus the margin is under the threshold while the later reading is at or above it. The cost fit SHALL be
adopted for the window when at least `usage_cost_min_pairs` gaps were judged and its false allows are not more than the flat figure's; otherwise the
window stays on the `units` basis, and the reason SHALL be kept: too few pairs with cost, too few gaps judged, more false allows than flat, or no fit.

#### Scenario: A weekly window that gains little

- **GIVEN** twelve usable weekly pairs whose gains per unit are 0, 0, 0.5, 0.5, 0.5, 1, 1, 0.5, 0, 1, 0.5 and 2, a floor of one, a minimum of eight, the default quantile and `usage_estimate_basis: units` for the weekly window
- **WHEN** the allowances are calibrated
- **THEN** the weekly allowance is 1 point per unit, not the default 2

#### Scenario: A session window that costs more than the default

- **GIVEN** ten usable session pairs whose gains per unit are all between 11 and 14 points, the default of 10 with a ceiling of 20 and `usage_estimate_basis: units`
- **WHEN** the allowances are calibrated
- **THEN** the session allowance is above 10 and not above 20

#### Scenario: Too few pairs

- **GIVEN** seven usable pairs for a window and a minimum of eight
- **WHEN** the allowances are calibrated
- **THEN** the window's configured allowance stands and nothing calibrated is applied

#### Scenario: A gap that is not a sample

- **GIVEN** readings whose gap holds no unit that spent, readings whose later figure is lower, readings less than `usage_cache_minutes` apart, and a gap longer than the window's span
- **WHEN** the flat pairs are made
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
- **THEN** each window uses its configured allowance on the `units` basis, as before the cost basis existed, and no fit is made or kept

#### Scenario: The basis is units

- **GIVEN** `usage_estimate_basis: units` for the session window and a record that would give it an adopted cost fit
- **WHEN** the allowances are calibrated
- **THEN** the session window keeps its flat allowance and no cost fit, and the kept reason is `basis_units`

#### Scenario: A cost fit from an exact record

- **GIVEN** twenty session cost pairs whose gain is exactly three points for each dollar recorded, with costs between $0.50 and $4.00 and the gaps of different lengths, and the intercept on
- **WHEN** the allowances are calibrated
- **THEN** the kept points per dollar is 3.00, the kept intercept per hour is 0.00 and the safety scale is 1

#### Scenario: An intercept for what is not recorded

- **GIVEN** twenty session cost pairs whose gain is 2 points per dollar plus 4 points for each hour of the gap, and the intercept on
- **WHEN** the allowances are calibrated
- **THEN** the kept points per dollar is 2.00 and the intercept per hour 4.00, and with the intercept off the fit is through the origin and its points per dollar is higher

#### Scenario: A negative coefficient is fitted at zero

- **GIVEN** cost pairs whose gains fall as the hours of the gap grow
- **WHEN** the fit is made with the intercept on
- **THEN** the intercept is zero and the points per dollar is the fit through the origin

#### Scenario: The safety scale keeps nine gaps in ten under the estimate

- **GIVEN** cost pairs with scatter around the line, so that a plain fit would be under the gain in about half of them
- **WHEN** the fit is made with a quantile of 0.9
- **THEN** the scale is above 1 and not above 2, and the gain of at least nine pairs in ten is not above the kept figures' prediction

#### Scenario: The weekly window is one figure

- **GIVEN** a hundred weekly cost pairs whose gains are 0, 1 or 2 points and the default settings
- **WHEN** the allowances are calibrated
- **THEN** the weekly cost fit is a single points-per-dollar figure with no intercept and no per-unit or per-role figure

#### Scenario: A gap with no cost is not a cost pair

- **GIVEN** a gap holding only a `login_refresh` record with no cost, and a gap in which a unit has records and none carries a cost
- **WHEN** the cost pairs are made
- **THEN** neither is a cost pair

#### Scenario: A gap with only unit-less spend is a cost pair

- **GIVEN** a gap in which the only records are a `plan` record with a cost and no unit
- **WHEN** the pairs are made
- **THEN** it is a cost pair and it is not a flat pair

#### Scenario: Too few pairs with cost

- **GIVEN** seven cost pairs for a window and `usage_cost_min_pairs` of eight
- **WHEN** the allowances are calibrated
- **THEN** no cost fit is made, the window keeps its flat figure and the reason is too few pairs with cost, with seven pairs held and eight needed

#### Scenario: Adopted when no worse than flat on false allows

- **GIVEN** twenty cost pairs over which the walk-forward cost estimate has one false allow and the flat one has three
- **WHEN** the allowances are calibrated
- **THEN** the cost fit is adopted for the window

#### Scenario: Not adopted when worse on false allows

- **GIVEN** twenty cost pairs over which the walk-forward cost estimate has three false allows and the flat one has one
- **WHEN** the allowances are calibrated
- **THEN** the window stays on the `units` basis, the cost fit is kept with its counts and the reason is more false allows than flat

#### Scenario: Too few gaps judged

- **GIVEN** twelve cost pairs and a minimum of eight, so that four gaps can be judged
- **WHEN** the allowances are calibrated
- **THEN** the cost fit is made and not adopted, and the reason is too few gaps judged, with four held and eight needed

#### Scenario: Settings

- **WHEN** the quantile is not above 0 or is above 1, a window or minimum is below 1, the minimum is above the window, a floor is negative or above the cap, an allowance is neither a whole number nor `auto`, `usage_estimate_basis` is neither `cost` nor `units`, `usage_cost_min_pairs` is below 1 or above `usage_allowance_window`, or `usage_cost_quantile` is not above 0 or is above 1
- **THEN** the configuration is refused naming the key

### Requirement: The calibrated allowances are computed once a tick and kept with their inputs

The framework SHALL compute the allowances at most once in a tick and keep the result, per window, in a state file beside the guard's cache file:
the flat figure with its quantile, the pairs used, the pairs available and the time, and the basis in force with the reason it is or is not `cost`,
the points per dollar, the intercept per hour and the safety scale, the cost pairs held, and the false allows of the cost fit and of the flat figure over
the gaps judged. The file SHALL carry a version (`2`) at the top: `{"version": 2, "windows": {...}}`. A reader of the previous shape, which keeps a
`Calibrated` object per window name at the top level, reads this file as no calibration. The reader of this version reads a file of the previous shape
as the flat calibration it was (basis `units`), and a file that is missing, unreadable, of a version it does not know or of another shape as no
calibration. No calibration is never an error. An estimate SHALL read that file and not recompute from the record, except that it reads the ledger
rows since the reading for their cost. The status command SHALL print, without a call, one line of the allowances in force and what is behind them:
for a window on the `cost` basis its points per dollar, its per-hour intercept when it has one, the safety scale and the cost pairs; for a window on the
`units` basis its flat figure and pairs, and, when `cost` was asked for and is not in force, why; or that the defaults stand and how many pairs are
needed, or that calibration is off.

#### Scenario: The status line

- **GIVEN** a kept result of 9 points for the session on 24 pairs and 1 for the weekly on 24 pairs, both on the `units` basis
- **WHEN** the status command is run
- **THEN** it prints `usage allowances: session 9/unit (24 pairs), weekly 1/unit (24 pairs), calibrated` and makes no call

#### Scenario: The cost basis in force

- **GIVEN** a session window on the `cost` basis at 2.65 points per dollar and 5.1 points an hour with a safety scale of 1.2 on 31 cost pairs, and a weekly window on the `units` basis at 1 point per unit on 24 pairs whose cost fit was not adopted because it had more false allows than flat
- **WHEN** the status command is run
- **THEN** it prints `usage allowances: session 2.65 points/$ + 5.1 points/h (31 pairs with cost, scale 1.2), weekly 1/unit (24 pairs; cost basis not adopted: more false allows than flat), calibrated` and makes no call

#### Scenario: Cost asked for and too few pairs with cost

- **GIVEN** a session window with a flat figure of 9 on 24 pairs and three cost pairs of eight needed
- **WHEN** the status command is run
- **THEN** the session part reads `session 9/unit (24 pairs; cost basis needs 8 pairs with cost, 3 held)`

#### Scenario: Defaults stand

- **GIVEN** a window with three usable pairs and a minimum of eight
- **WHEN** the status command is run
- **THEN** the line says the defaults stand and that three pairs of eight are held

#### Scenario: Calibration off

- **GIVEN** `calibrate_usage_allowances: false`
- **WHEN** the status command is run
- **THEN** it prints `usage allowances: fixed (calibration off)`

#### Scenario: A damaged file

- **GIVEN** a state file that cannot be read
- **WHEN** an estimate is made
- **THEN** the configured allowances are used and the tick does not fail

#### Scenario: A file of the previous shape

- **GIVEN** a file written by the previous version, a `Calibrated` object per window name at the top level
- **WHEN** an estimate is made and the status command is run
- **THEN** the flat figures in it are applied on the `units` basis, the line says so, and the next tick rewrites the file in the version 2 shape

#### Scenario: The previous reader reads the new file

- **GIVEN** a file in the version 2 shape
- **WHEN** the previous reader reads it
- **THEN** it returns no calibration and does not fail

#### Scenario: A version this reader does not know

- **GIVEN** a file whose version is 3
- **WHEN** it is read
- **THEN** it means no calibration, not an error

#### Scenario: Computed once

- **GIVEN** a tick in which two units ask to start
- **WHEN** both are decided
- **THEN** the record is read for the allowances once

### Requirement: The usage replay re-runs the estimator over the recorded history

`abk usage replay` SHALL re-run the estimate over the recorded readings and ledger without a model call, a call to the usage
endpoint or a write, and print for each window and each usable gap (optionally from `--since`) the reading before, the reading after, the units, and the estimate made from the first, and per window the counts of underestimates, of actual readings beyond the estimate plus the margin, of false pauses (an estimate refused by the headroom rule while the next actual reading was under the threshold) and of false allows. The allowance replayed
SHALL be the one calibration would have given from the pairs before each gap, unless `--session-allowance` or `--weekly-allowance` fixes
one, and `--margin` SHALL replace the margin; the threshold SHALL be the window's configured pause percent, and the output SHALL say so. Those rows and
counts are the flat per-unit estimate. For each gap that is a cost pair after the first `usage_cost_min_pairs` cost pairs, each row SHALL also give the
cost recorded in the gap and the estimate the cost fit made from the cost pairs before it gives, and per window two further lines SHALL give the same
four counts and the mean overshoot for the flat estimate and for the cost estimate over those gaps, so that the two are compared on the same gaps. The
replay SHALL end with the verdict the calibration would reach for each window: the cost basis adopted, or not adopted and why, by the same rule.

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

#### Scenario: Flat against cost

- **GIVEN** a record of twenty session cost pairs and a minimum of eight, in which the flat estimate overestimates every gap and the cost estimate has one false allow
- **WHEN** it is replayed
- **THEN** each of the twelve gaps after the first eight shows the cost recorded and the cost estimate, the session has a flat line and a cost line over those twelve gaps each with underestimates, misses beyond the margin, false pauses and false allows, and the flat line has more false pauses and fewer false allows

#### Scenario: The cost fit is walk-forward

- **GIVEN** the same record
- **WHEN** it is replayed
- **THEN** the cost estimate of each gap is made from the fit of the cost pairs before it only, as the flat allowance is

#### Scenario: Too few cost pairs to judge

- **GIVEN** a window with seven cost pairs and a minimum of eight
- **WHEN** it is replayed
- **THEN** its rows carry no cost estimate, no cost line is printed, and the verdict says the cost basis is not adopted for too few pairs with cost, with seven held and eight needed

#### Scenario: The verdict

- **GIVEN** a record whose cost estimate has more false allows than the flat one over the gaps judged
- **WHEN** it is replayed
- **THEN** the verdict for the window says the cost basis is not adopted because it has more false allows than flat
