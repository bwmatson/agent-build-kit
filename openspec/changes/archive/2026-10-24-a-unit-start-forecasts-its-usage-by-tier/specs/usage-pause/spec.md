## ADDED Requirements

These requirements are added, not substituted for the estimate requirements, because `usage-is-estimated-from-recorded-cost` modifies
those (the estimate adds what was spent since the reading, the cap, the reset, the calibration, the replay). This change adds what a unit
admitted is expected to spend. It builds on that change's `points_per_usd`, the figure its kept calibration holds for a window whose
basis in force is `cost`, and on its replay; it leaves its `estimate_steps` key in the cache file as it is.

In every scenario below, a *fixture history* is a set of units with a final verdict whose ledger rows have the costs named, a
`points_per_usd` of 2.5 for both windows, a margin of 5, a session threshold of 80 and `usage_forecast_quantile` 0.5 (which adds nothing
to a rate), unless a scenario says otherwise.

### Requirement: A start is forecast from the recorded history of the unit's review tier

With `usage_forecast` on, the guard SHALL forecast what a unit about to start will spend as, over every cell (role, node, round and
model) that units of its review tier ran in the recorded history, the share of those units that ran the cell at least once times the
mean incremental cost of the calls in the cell, summed, and then times the `points_per_usd` of each window. A unit's tier SHALL be the
review tier stored on it by the planner; its history SHALL be the units of that tier with a final verdict record, read from the
verdict record by unit id and never from the ledger's own `tier` field, which is the test kind. A cell the tier's units never ran
SHALL NOT be in the sum. When each of two size bands of the tier's history (units at or below and above its median changed lines) has at least the
minimum number of units, the unit SHALL be forecast from the band its estimated lines fall in, and otherwise from the whole tier.

#### Scenario: An auto unit is admitted where a full unit is refused at the same reading

- **GIVEN** a held reading with the session at 67% and a threshold of 80, and a fixture history of twenty `auto` units, each of which ran tests ($0.80), implement ($0.60) and a review round 1 ($1.00), six of which ran a review round 2 ($0.50), and twenty `full` units that ran the same and in which eighteen ran a review round 2 ($0.50), six a review round 3 ($0.40) and eighteen a rework round 0 ($0.50)
- **WHEN** an `auto` unit and then a `full` unit ask to start with the read refused
- **THEN** the `auto` forecast is $2.55, 6.4 points, and 67 plus 6.4 plus 5 is under 80, so it is allowed; the `full` forecast is $3.42, 8.6 points, and 67 plus 8.6 plus 5 is not, so it is refused

#### Scenario: A second round costs less than the first

- **GIVEN** the `full` fixture history
- **WHEN** the review cells of a `full` unit are forecast
- **THEN** they come to $1.00 plus 0.9 times $0.50 plus 0.3 times $0.40, $1.57, and not three rounds at $1.00 nor $2.20 from the rounds' chances at the first round's cost

#### Scenario: A cell the tier never ran

- **GIVEN** the `auto` fixture history, in which no unit ran a rework
- **WHEN** an `auto` unit is forecast
- **THEN** no rework cell is in the forecast

#### Scenario: The history is by planned review tier and not by test kind

- **GIVEN** units whose ledger rows carry `tier` of `unit-test` and `e2e-test`, and verdict records whose planned tiers are `auto` and `full`
- **WHEN** the history of `auto` is gathered
- **THEN** it holds the units whose verdict record planned `auto`, whatever test kind their rows carry

#### Scenario: A unit still running is not in the history

- **GIVEN** a unit with a review round 1 call and no final verdict record
- **WHEN** a tier's history is gathered
- **THEN** it is in no tier's history and no cell counts it

#### Scenario: Size refines the tier when each band has enough

- **GIVEN** `usage_forecast_min_runs` of 10, twenty units of a tier of which ten are at or below the median changed lines and ten above, the larger ten having each run a review round 2 and the smaller ten none
- **WHEN** a unit of that tier with estimated lines above the median is forecast
- **THEN** its review round 2 has a chance of 1, and for a unit at or below it a chance of 0

#### Scenario: Size is not used when a band is thin

- **GIVEN** the same twenty units but of which only nine are above the median
- **WHEN** a unit above the median is forecast
- **THEN** the whole tier's history is used

### Requirement: A tier with too little history is forecast at the flat allowance

A tier SHALL be forecast from its history only when it has at least `usage_forecast_min_runs` (default 10) units with a final verdict, and
a cell SHALL have that many calls to use its own mean; a cell with fewer SHALL use the mean of the same role, node and round over every
model, and a step with fewer than that the mean of its node. A unit whose tier has fewer units than the minimum, a unit with no stored
review tier, and a window with no `points_per_usd` (its basis in force is `units`: the setting says so, calibration is off, too few pairs hold a cost, or the fit was not adopted) SHALL be forecast at the prior:
the flat per-unit allowance of the window as the estimate counts it. The status line and a refusal SHALL say when the prior is in use.
A tier SHALL NOT be forecast at zero for want of history.

#### Scenario: A tier under the minimum uses the prior

- **GIVEN** `usage_forecast_min_runs` of 10, nine `full` units in the history and a calibrated session allowance of 11 points
- **WHEN** a `full` unit is forecast for the session window
- **THEN** the forecast is 11 points and the line says it is the prior

#### Scenario: Another tier with enough units is not affected

- **GIVEN** the same history with twenty `auto` units
- **WHEN** an `auto` unit is forecast
- **THEN** the forecast is from the `auto` units' own history

#### Scenario: A thin cell widens its mean

- **GIVEN** a review round 3 cell with four calls under the current model and 23 over every model
- **WHEN** the cell's cost is taken
- **THEN** it is the mean over every model of that role, node and round

#### Scenario: No conversion to points

- **GIVEN** a window whose basis in force is `units`, so with no `points_per_usd`
- **WHEN** a unit is forecast
- **THEN** that window's forecast is its flat allowance and the reason of a refusal says the prior was used

#### Scenario: A unit with no stored tier

- **GIVEN** a unit planned with review off, so with no review tier
- **WHEN** it is forecast
- **THEN** it is forecast at the flat allowance

### Requirement: The chance of a later round is an upper bound at a high quantile

The chance used that a unit reaches a cell SHALL be its observed share plus `z(q)` standard errors, `q` being `usage_forecast_quantile`
(default 0.9, above 0 and at most 1), capped at 1, with the standard error taken from the share smoothed by one success and one failure,
`(k+1)/(n+2)` for `k` of `n`, so that it is never zero; at a `q` of 0.5 it SHALL be the observed share. The chances of the rounds of one
step SHALL be made non-increasing in the round. The cost of a step SHALL be the mean, not a quantile.

#### Scenario: A thin history is read cautiously

- **GIVEN** a `q` of 0.9 and a cell reached by 3 of 10 units
- **WHEN** the chance is taken
- **THEN** it is above 0.3 and at most 1

#### Scenario: More units narrow the margin

- **GIVEN** a cell reached by 30% of units, for 10 units and then for 200
- **WHEN** the chances are taken at a `q` of 0.9
- **THEN** the chance for 200 units is below the chance for 10 and above 0.3

#### Scenario: A quantile of one half adds nothing

- **GIVEN** `usage_forecast_quantile` of 0.5
- **WHEN** a cell reached by 6 of 20 units is taken
- **THEN** its chance is 0.3

#### Scenario: A later round is never likelier than an earlier one

- **GIVEN** observed shares of 0.2 for a review round 2 and 0.2 for a round 3 with fewer units in round 3
- **WHEN** the chances are taken
- **THEN** the round 3 chance is not above the round 2 chance

#### Scenario: Settings out of range

- **WHEN** `usage_forecast_quantile` is 0 or above 1, or `usage_forecast_min_runs` is below 1
- **THEN** the configuration is refused naming the key

### Requirement: A unit past its expected rounds is counted at what it spent

What a unit has spent is in the ledger and is counted by the estimate; the forecast SHALL add only what is still to come. For a unit that
has run `r` rounds of a step, the forecast of later rounds SHALL be, over the rounds `k` after `r`, the chance of reaching `k` divided by
the chance of reaching `r`, times the mean cost of round `k`: the chance given that the unit has got this far. It SHALL NOT subtract
what the unit spent above the tier's average, SHALL NOT discount a unit for being ahead of it, and SHALL be zero beyond the last round the
step has (`max_review_rounds` for the review) or the last the cell's history has. At a gate after a unit's first, the forecast of the unit
SHALL be the step asked, at the cell's mean cost, and not the whole path.

#### Scenario: A unit at its last review round

- **GIVEN** the `full` fixture history and a `full` unit that asks for its review round 3 with `max_review_rounds` of 3
- **WHEN** it is forecast at that gate
- **THEN** the forecast of the unit is $0.40, the cost of the step asked, and nothing for a round 4

#### Scenario: A unit that went further than most

- **GIVEN** the `full` fixture history and a `full` unit that has run two review rounds and has spent $4.50
- **WHEN** what is still to come is forecast
- **THEN** it is 6/18 times $0.40, $0.13, and the $4.50 is neither subtracted nor discounted

#### Scenario: A later gate asks for its step

- **GIVEN** a unit admitted earlier and now asking to run its review round 2
- **WHEN** the gate decides
- **THEN** the unit's own forecast is the round 2 cell at $0.50 and not 0.9 times $0.50

### Requirement: A running unit contributes the remaining expected cost of its current step

A call is written to the ledger only when it ends, so the guard SHALL record, when it admits an agent step of a unit, a step row (unit,
node, round, time) in the forecast record, and SHALL treat a unit whose latest step row has no later ledger row of that unit, node and
round as running that step. Such a unit SHALL contribute, to every other ask, the cost of that step's cell times the greater of one
less the share of the cell's mean duration that has elapsed and one tenth, converted to points. The unit asking SHALL NOT be counted as
running. A unit with no step row SHALL contribute nothing, and the status line SHALL say how many running units have none. For a unit admitted on an estimate that has no ledger row since the reading, whose flat per-unit allowance the estimate counts until its first call ends, the unit's remainder SHALL replace that allowance when it has a step row, so that the same running step is never counted twice.

#### Scenario: A step half done

- **GIVEN** a review round 1 cell costing $1.00 with a mean duration of ten minutes, and a unit admitted to that step four minutes ago whose call has not ended
- **WHEN** another unit asks to start
- **THEN** the running unit adds $0.60, 1.5 points, to the forecast

#### Scenario: A step past its mean duration

- **GIVEN** the same cell and a unit twenty minutes into the step
- **WHEN** another unit asks to start
- **THEN** the running unit adds one tenth of $1.00

#### Scenario: A finished step adds nothing

- **GIVEN** a unit whose step row has a ledger row of the same unit, node and round at or after it
- **WHEN** another unit asks to start
- **THEN** the unit adds nothing, as its spend is in the estimate

#### Scenario: The asking unit is not running

- **GIVEN** a unit with a step row asking to run its next step
- **WHEN** the gate decides
- **THEN** its own earlier step is not added as a running unit

#### Scenario: The remainder replaces the flat allowance of an admitted unit with no record

- **GIVEN** a window on the `cost` basis, in which a unit admitted on an estimate with no ledger row since the reading is counted at the flat per-unit allowance, and that unit has a step row
- **WHEN** another unit asks to start
- **THEN** the unit adds its step's remainder and not the flat allowance as well, and a unit with no step row is still counted at the flat allowance

#### Scenario: A running unit with no step row

- **GIVEN** a running unit from before the record existed
- **WHEN** a unit asks to start
- **THEN** it adds nothing and the status line counts it as unrecorded

### Requirement: A plan call and a track due within a window reserve their expected cost

The guard SHALL reserve, for each window, the expected cost, from the ledger's `plan` and `track_*` cells at their mean, of a plan call
that is due (the pipeline has a change to plan) and of each scheduled track whose installed timer next fires before that window's reset,
`track_propose` being included with a track that proposes. A reservation SHALL be converted with the window's `points_per_usd` and
SHALL be released when its row is written. A track whose timer cannot be read SHALL be reserved for nothing, and the status line SHALL
say the timers were not read. A track or plan ask SHALL itself be forecast as one call at its mean cost and judged like a unit.

#### Scenario: A due track reserves room

- **GIVEN** a held reading with the session at 70%, a threshold of 80, a margin of 5, a daily `track_health` cell at $2.00 and 2.5 points per dollar, and the health timer firing in an hour before the session resets
- **WHEN** an `auto` unit forecast at $1.00 asks to start
- **THEN** the track reserves 5 points and the unit forecast is 2.5, and 70 plus 5 plus 2.5 plus 5 is not under 80, so it is refused and the reason names the reservation, where without the track 70 plus 2.5 plus 5 would be allowed

#### Scenario: A track outside the window

- **GIVEN** the same track whose timer next fires after the session window resets
- **WHEN** the session window is judged
- **THEN** the track reserves nothing for the session window, and reserves for the weekly window if it fires before that resets

#### Scenario: A plan call due

- **GIVEN** a change to plan and a `plan` cell at $0.20
- **WHEN** a unit asks to start
- **THEN** $0.20 of points is reserved

#### Scenario: A reservation is released

- **GIVEN** a track reserved and then its `track_health` row written
- **WHEN** a unit asks to start
- **THEN** the track no longer reserves, its cost being in the estimate

#### Scenario: Timers that cannot be read

- **GIVEN** a machine where the timers' next times cannot be read
- **WHEN** a unit asks to start
- **THEN** no track is reserved and the status line says so

### Requirement: A start is refused when its forecast and the margin do not fit under the threshold

On a fresh or held reading as well as on an estimate, a start SHALL be refused for a window when its estimate plus the forecast of the
unit, the running units' remainders and the reservations, plus the margin, is not under the window's threshold. On a reading the forecast
SHALL apply only after the reading has allowed the start, so it can only make an answer stricter; on an estimate it SHALL be added to
the window's estimate. The refusal's reason SHALL carry the estimate's text, the window, the forecast in points and the role and node
(with the round) that contribute most points among the unit's own cells, the running units and the reservations, and SHALL name a prior
when one was used. A refused unit SHALL be stopped as any refused start is. With `usage_forecast` off no forecast SHALL be made and
the decision SHALL be what it was.

#### Scenario: The refusal names the role

- **GIVEN** the `full` fixture history, a session estimate of 67% and a `full` unit asking to start
- **WHEN** it is refused
- **THEN** the reason holds the estimate, says the session forecast is 8.6 points, and names the review node's round 1 as the largest contribution

#### Scenario: A reservation is the largest

- **GIVEN** a track reserving 5 points against a unit forecast at 3
- **WHEN** the start is refused
- **THEN** the reason names the track as the largest contribution

#### Scenario: A live reading is judged too

- **GIVEN** a live reading of 70% under a threshold of 80 and a `full` unit forecast at 8.6 points
- **WHEN** the unit asks to start
- **THEN** it is refused for the forecast though the reading alone allows it, and an `auto` unit forecast at 3 points is allowed

#### Scenario: The forecast only makes an answer stricter

- **GIVEN** a reading the guard refuses by its threshold
- **WHEN** a unit is forecast at zero
- **THEN** it is refused for the threshold, as before

#### Scenario: The guard is off or the forecast is

- **GIVEN** `usage_forecast` false, and then the guard off
- **WHEN** a unit asks to start in each
- **THEN** the decision is the one made without a forecast

#### Scenario: A weekly window is the one that overruns

- **GIVEN** a session window with ample room and a weekly estimate of 86 against a threshold of 92, which with the margin of 5 is ample (91), and a unit forecast at two points of the weekly window
- **WHEN** the unit asks to start
- **THEN** it is refused for the weekly window and the reason names it

### Requirement: The emergency lane and the cap on starts are unchanged

The usage guard SHALL NOT read a unit's priority: a priority-0 unit SHALL be forecast and refused or admitted as any other, with no
exemption from the threshold and no extra margin, and the emergency lane (`emergency_extra`) SHALL go on lifting only the limits on units
and workers. A unit running in the lane SHALL be a running unit like any other. At most `usage_estimate_max_starts` units SHALL be
admitted on an estimate for one reading; a start the cap refuses SHALL be refused though it fits, and a start the forecast refuses SHALL
NOT count towards the cap. A unit's admission SHALL be recorded as before.

#### Scenario: A priority-0 unit is held by usage like any other

- **GIVEN** the `full` fixture history, a session estimate of 67% and a priority-0 `full` unit with the emergency lane having room
- **WHEN** it asks to start
- **THEN** it is refused as a priority-3 `full` unit is, and a priority-0 `auto` unit is allowed as a priority-3 one is

#### Scenario: The lane's unit counts as running

- **GIVEN** a priority-0 unit admitted and running a step, and another unit asking to start
- **WHEN** the other is forecast
- **THEN** the lane unit's remaining step is added as for any running unit

#### Scenario: The cap holds though the forecast fits

- **GIVEN** a cap of three, three units admitted on an estimate for the reading, and a fourth whose forecast fits
- **WHEN** the fourth asks
- **THEN** it is refused for the cap, and the reason says three starts have been made

#### Scenario: A forecast refusal is not a start

- **GIVEN** a cap of three, two units admitted and a `full` unit refused for its forecast
- **WHEN** an `auto` unit that fits asks
- **THEN** it is admitted as the third

### Requirement: The status command shows the forecast beside the estimate

`abk status` SHALL print, after each account's estimate line and without a call, a `forecast:` line giving, for each window, the forecast
in points of a unit of each review tier with the number of units that history rests on or `prior`, the units running with their remaining
points and how many have no step row, and the reservations with the timers read or not. It SHALL print nothing when `usage_forecast` is
off or the runtime has no usage window.

#### Scenario: The line

- **GIVEN** the fixture histories, one unit running and a track reserved
- **WHEN** `abk status` runs
- **THEN** it prints each tier's session and weekly forecast with its unit count, the running unit's remaining points and the reservation, after the estimate line

#### Scenario: A tier on the prior

- **GIVEN** a tier with five units
- **WHEN** `abk status` runs
- **THEN** its figure is marked as the prior

#### Scenario: Forecast off

- **GIVEN** `usage_forecast` false
- **WHEN** `abk status` runs
- **THEN** no forecast line is printed and the other usage lines are as before

#### Scenario: A runtime with no window

- **GIVEN** a runtime with no usage window
- **WHEN** `abk status` runs
- **THEN** no forecast line is printed
