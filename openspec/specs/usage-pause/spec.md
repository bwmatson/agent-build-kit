# usage-pause Specification

## Purpose
Defines what happens when a step ends having written nothing while the account's usage
is exhausted: the unit is paused in the existing shape, not failed.

## Requirements

### Requirement: An empty step is judged against the usage window before it fails

When a step ends having produced nothing, the pipeline SHALL consult the usage reading
it already holds, and where the account's window is exhausted SHALL leave the unit in
the same state, with the same note wording and the same record of where to continue, as
a unit stopped between steps for that reason — not as a failure. The reading SHALL be
one the pipeline already has rather than a new call, and no usage SHALL be read while a
step is running.

#### Scenario: A quiet refusal

- **WHEN** a step ends having written nothing and the usage window is exhausted
- **THEN** the unit is paused, recorded as a stop between steps is recorded, and set to
  continue at that step

#### Scenario: Shown as a pause

- **WHEN** such a unit is drawn on the unit graph
- **THEN** it appears as stopped for usage rather than failed

#### Scenario: An empty step with usage to spare

- **WHEN** a step ends having written nothing and the window is healthy
- **THEN** this requirement does not apply and the outcome is decided elsewhere

### Requirement: Running steps are still never interrupted

The pipeline SHALL NOT stop, kill or re-check a step that is already running on account
of usage. Usage SHALL continue to be checked only when deciding whether to begin a step.

#### Scenario: The window fills during a long step

- **WHEN** the window crosses its threshold while a step is running
- **THEN** that step runs to completion, and only the next step's start is gated

### Requirement: A paused unit resumes through the mechanism that exists

A unit paused this way SHALL be picked up by the resume the pause already schedules,
keeping its branch, its commits and any feedback, and SHALL resume at the step that did
not finish — with no recovery mechanism added for it.

#### Scenario: After the window resets

- **WHEN** the scheduled resume runs
- **THEN** the unit may be built in that pass and continues at the step it stopped in,
  with its earlier commits intact

### Requirement: Every use of the usage endpoint is recorded

Each call to the usage endpoint, and each reading answered from the cache, SHALL be recorded with the time, the caller, the
outcome (ok, rate limited, timeout, error or from the cache), the status code, the latency, and any rate-limit or retry headers
of the answer, including on a refusal. The record SHALL be a file in the state directory that is not committed, SHALL hold no token, SHALL be kept for a week,
and SHALL NOT be rolled up when a change is archived. Every reader of the endpoint SHALL be recorded, each under its own
caller.

#### Scenario: A call that is refused

- **WHEN** the endpoint answers with a rate-limit status
- **THEN** the record gains a line with that status, the latency and every rate-limit or retry header of the answer

#### Scenario: An answer from the cache

- **WHEN** a start is answered from a cached reading
- **THEN** the record gains a line marked as from the cache, with the reading's age

#### Scenario: Another reader

- **WHEN** the runtime's usage status or the tracks runner reads usage
- **THEN** the record gains a line naming that caller

#### Scenario: The token

- **WHEN** the record is read
- **THEN** it holds no token

### Requirement: The call rate is shown, and from it a safe rate is inferred

The pipeline SHALL derive from the record, over the last hour and the last day, the calls by outcome and caller, the share
answered from the cache, the refusals and the last one's time, for each refusal the quiet time before it and the calls in the
fifteen minutes before it, and the shortest interval between successful calls not followed by a refusal. The status command SHALL
print them in one line, and the figures SHALL be exported as a metric, the interval as a gauge in whole seconds.

#### Scenario: A refusal after many calls

- **GIVEN** a run of calls closely spaced followed by a refusal
- **WHEN** the reading is derived
- **THEN** it shows the refusal, the calls in the fifteen minutes before it, and the quiet time before it

#### Scenario: No refusals

- **GIVEN** a day with calls and no refusals
- **WHEN** the reading is derived
- **THEN** it shows the calls, the shortest interval used, and no refusals

#### Scenario: The status line

- **WHEN** the status command is run
- **THEN** one line gives the calls in the last hour, the refusals, the cache's hit share and the interval in use

### Requirement: The time a reading is kept adapts within bounds

The time a good reading is kept SHALL start at its configured value, SHALL double after a refusal up to a configured maximum,
SHALL respect the retry time a refusal names when it is longer, SHALL NOT double after a refusal whose answer names a retry time of zero (the host asking for no wait, which says nothing about the rate of calls), and SHALL halve after the same time without a refusal, never
below the configured value. The configured maximum SHALL default to thirty minutes. The status command SHALL say the interval in use and what set it.

#### Scenario: A refusal

- **GIVEN** a reading kept for fifteen minutes
- **WHEN** a call is refused
- **THEN** the time becomes thirty minutes, and the status command says it followed a refusal

#### Scenario: A long quiet

- **GIVEN** a time of thirty minutes and thirty minutes without a refusal
- **WHEN** the time is next read
- **THEN** it is fifteen minutes

#### Scenario: The maximum

- **GIVEN** a time at the maximum
- **WHEN** another refusal happens
- **THEN** the time stays at the maximum

#### Scenario: A retry time that is longer

- **GIVEN** a refusal whose answer names a retry time longer than the doubled interval
- **WHEN** the next call is due
- **THEN** no call is made before the retry time

#### Scenario: A refusal that asks for no wait

- **GIVEN** a reading kept for fifteen minutes
- **WHEN** a call is refused with a retry time of zero
- **THEN** the time stays fifteen minutes, the cool-down is the short default and not zero, and the status command says the refusal did not widen it

#### Scenario: A refusal that names no retry time

- **GIVEN** a reading kept for fifteen minutes
- **WHEN** a call is refused and the answer names no retry time
- **THEN** the time becomes thirty minutes, as in the first scenario, and a second refusal leaves it at the default maximum of thirty minutes

### Requirement: The usage endpoint is asked only when a fresh reading could change a decision

For a decision to start work or to resume paused work, the guard SHALL use the reading it holds when that
reading settles the decision, and SHALL ask the endpoint only when a fresh reading could change it. A refusal made on a reading of
a window that has not reset SHALL stand without a call, an allowance SHALL stand while the usage could not have reached the
threshold since the reading, and a reading of a window that has reset SHALL not be used. Before the endpoint is asked, a fresh reading
in Claude Code's own usage cache SHALL be used when the usage-pause requirement for it applies.

#### Scenario: Far from the threshold

- **GIVEN** a reading of twenty percent used, a threshold of ninety-two and three hours to the reset
- **WHEN** a unit asks to start, even though the cached reading is older than the cache time
- **THEN** it is allowed and the endpoint is not called

#### Scenario: A window already used up

- **GIVEN** a reading at or over the threshold in a window that has not reset
- **WHEN** units ask to start
- **THEN** they are refused without a call, until the time the threshold is worked out to reach the reading or the window resets

#### Scenario: Close to the threshold

- **GIVEN** a reading whose headroom is less than the usage that could have been added since it was taken
- **WHEN** a unit asks to start
- **THEN** the endpoint is asked

#### Scenario: The window has reset

- **GIVEN** a reading whose window reset has passed
- **WHEN** a unit asks to start
- **THEN** the endpoint is asked

#### Scenario: No reading

- **WHEN** the guard holds no reading
- **THEN** the endpoint is asked

#### Scenario: A fresh reading in Claude Code's own cache

- **GIVEN** no reading of the guard's own that settles the decision, and a block in Claude Code's own cache fetched four minutes ago
- **WHEN** a unit asks to start
- **THEN** the decision is made from that block and the endpoint is not asked

### Requirement: How much usage could have been added comes from the fastest climb seen

The most usage that could have been added since a reading SHALL be the fastest climb, in percentage points a minute, seen for that
window in the record of readings, times the minutes since the reading, with a margin, and SHALL be no less than a configured floor.

#### Scenario: A pipeline with a history

- **GIVEN** a record in which the session window climbed at most three points a minute
- **WHEN** the most usage added since a reading ten minutes old is worked out
- **THEN** it is thirty points plus the margin

#### Scenario: A pipeline with no history

- **GIVEN** no record
- **WHEN** it is worked out
- **THEN** the configured floor is used

### Requirement: The endpoint is not asked more often than the interval allows

The guard SHALL NOT call the endpoint more often than the cache interval, and when a decision needs a fresh reading inside that
interval it SHALL refuse the start for the time left to the next permitted call, with a reason that says so, and not make a call, unless the estimate rule for a refused or unreadable read allows the start.

#### Scenario: A decision that needs a reading too soon

- **GIVEN** a call made two minutes ago and a decision close to the threshold
- **WHEN** a unit asks to start
- **THEN** it is refused for the time left to the next permitted call, and the endpoint is not called

#### Scenario: A decision that needs a reading too soon but has ample headroom

- **GIVEN** a call refused two minutes ago, a kept reading far under both thresholds and the minimum interval not yet passed
- **WHEN** a unit asks to start
- **THEN** the endpoint is not called and the start is decided by the estimate, not refused for the time left

### Requirement: The status command shows the held reading and calls only when asked

The status command SHALL print the reading it holds with its age and source, and SHALL call the endpoint only when asked to refresh.

#### Scenario: Status without refresh

- **WHEN** the status command is run with a held reading
- **THEN** it prints the reading and its age and makes no call

#### Scenario: Status with refresh

- **WHEN** the status command is run asking for a refresh
- **THEN** the endpoint is asked, subject to the interval

### Requirement: A round asks for no reading on behalf of units that cannot start in it

A round SHALL ask for a reading only for a decision about a unit that can start in it. A unit left out of the round by `--only`,
by a lease or by a backoff SHALL NOT cause one.

#### Scenario: Every candidate excluded

- **GIVEN** a round whose only candidates are left out by `--only`, a lease or a backoff
- **WHEN** the round decides whether to admit builds
- **THEN** the endpoint is not asked and no pause is written

### Requirement: A pause never names a time that has passed

A usage pause SHALL NOT end before the moment it is written. Its end SHALL be the later of the time computed from
the reading and now plus the unknown-retry interval, the grace period SHALL be applied once, and a reset time that
is not in the future SHALL be treated as unknown.

#### Scenario: A reset time in the past

- **GIVEN** a reading whose window reset time has already passed
- **WHEN** a pause is written from it
- **THEN** its end is after now by the unknown-retry interval, and the grace period is counted once

#### Scenario: A reset time in the future

- **GIVEN** a reading whose window resets in two hours
- **WHEN** a pause is written from it
- **THEN** its end is that reset time plus the grace period, once

#### Scenario: The spend limit and credits

- **GIVEN** a reached spend limit whose reset time has passed
- **WHEN** a pause is written
- **THEN** its end is not before now

### Requirement: A stale reading pauses briefly and says why

A cached reading older than the allowed age SHALL refuse a start and SHALL pause for the stale-retry interval
(five minutes by default, configurable), with a reason that says the reading is stale and where it came from. It SHALL NOT take the pause's end from the
stale reading's window.

#### Scenario: A reading six hours old

- **GIVEN** the only reading is six hours old and is not one the guard's own cache kept
- **WHEN** a unit asks to start
- **THEN** it is refused for the stale-retry interval, the reason says the reading is stale, and the next round asks
  again

#### Scenario: A reading served from the cache file

- **GIVEN** a reading kept in the cache file
- **WHEN** a unit asks to start
- **THEN** the reading's source says it came from the cache, not that it is live, and the staleness test applies to it

#### Scenario: A kept reading six hours old

- **GIVEN** a reading six hours old kept in the guard's own cache, of windows that have not reset, and a refused read
- **WHEN** a unit asks to start
- **THEN** the stale rule does not decide it: the estimate does, and the editor's reading is never the basis of one

### Requirement: A good usage reading is cached for a configured time

The guard SHALL keep a good live usage reading for a configured time, fifteen minutes by default, SHALL answer every reader
from it during that time, in every process, and SHALL NOT keep a reading past the reset of the window it describes.

#### Scenario: Several starts within the time

- **GIVEN** a good live reading fetched a few minutes ago
- **WHEN** many units ask to start, and the status command is run
- **THEN** the endpoint is not called again

#### Scenario: A configured time

- **GIVEN** a configuration that sets the time to five minutes
- **WHEN** a reading is six minutes old
- **THEN** the endpoint is asked again

#### Scenario: A window resets

- **GIVEN** a reading whose window resets in two minutes
- **WHEN** it is three minutes later
- **THEN** the reading is no longer used and the endpoint is asked

### Requirement: A failed live read is absorbed before anything pauses

When the live usage call fails, the guard SHALL retry it once after a short delay if the failure was a timeout or a connection error, and SHALL make no call until the time the host names, or a short default, after a rate-limit answer. It SHALL then use the last good live
reading while it is younger than the fallback age, and only then the editor's cached reading. A last good reading older than the fallback age SHALL NOT cover the failed call as a reading: it stands only through the estimate, which the usage-pause requirement for a refused or unreadable read defines. The reason a start
was refused SHALL name the source it rested on, and the cause of a failed live call SHALL be logged once per tick.

#### Scenario: The host answers that it is rate limited

- **GIVEN** a live call answered with a rate-limit status
- **WHEN** units ask to start during the cool-down
- **THEN** no further call is made, the last good live reading is used, and the reason names the rate limit and when the
  next call will be made

#### Scenario: One request fails

- **GIVEN** a live call that fails once and then succeeds
- **WHEN** a unit asks to start
- **THEN** the second answer is used and nothing is paused for staleness

#### Scenario: The live call keeps failing

- **GIVEN** a live call that keeps failing and a good live reading ten minutes old
- **WHEN** a unit asks to start
- **THEN** that reading is used, the reason names it, and the failure's cause is logged

#### Scenario: Nothing recent

- **GIVEN** a failing live call, no good live reading within the fallback age, an old editor reading, and no kept reading an estimate can rest on
- **WHEN** a unit asks to start
- **THEN** the start is refused as stale for the stale-retry interval

### Requirement: A refused start stops only that unit

A start refused for usage SHALL pause only the unit that asked. The pass SHALL continue its rounds, recording
merges, comments and state, SHALL ask the guard again at each round, SHALL admit builds as soon as it allows,
and SHALL resume units paused for usage within the same pass.

#### Scenario: A transient refusal

- **GIVEN** two units refused for a stale reading
- **WHEN** the next round's reading is current and allows builds
- **THEN** both resume within the same pass

#### Scenario: A merge during a pause

- **GIVEN** a unit paused for usage and a pull request merged meanwhile
- **WHEN** the next round runs
- **THEN** the merge is recorded in that round without waiting for the pass to end

#### Scenario: A refusal by the model

- **GIVEN** a `rate_limit` pause written because the model refused a build
- **WHEN** the next round runs before its deadline
- **THEN** no new build is admitted, as before: only a usage pause is limited to the unit that asked

#### Scenario: Real exhaustion

- **GIVEN** a reading that says the window is used up
- **WHEN** units ask to start
- **THEN** every start is refused each round until the guard allows

### Requirement: The pause line is never in the past

The line announcing a pause SHALL give its end in local time with the reason, and the end SHALL NOT be earlier
than the moment the line is printed.

#### Scenario: Printed deadline

- **WHEN** a pause is announced
- **THEN** the time shown is after the time it is printed

### Requirement: One process refreshes the usage reading

At the expiry of the cached reading one process SHALL call the usage endpoint, holding a lock around reading the cache,
calling and writing it, and SHALL read any cool-down under that lock. A process that finds the lock held SHALL serve the
last good reading and SHALL NOT call. However many readers ask, the endpoint SHALL be called at most once in the cache time.

#### Scenario: Several readers at expiry

- **GIVEN** a cached reading that has just expired and several threads and processes asking for usage at once
- **WHEN** they all ask
- **THEN** the endpoint is called once and the others are served the last good reading

#### Scenario: Twenty ticks in the cache time

- **GIVEN** a good reading and the default cache time
- **WHEN** twenty ticks ask within fifteen minutes
- **THEN** the endpoint is called once

### Requirement: Only the usage module refuses a usage start

Outside a `rate_limit` pause, a pause marker SHALL NOT refuse a start. Every start, in the tick, the pass and the gate,
SHALL be decided by asking the usage module, and the marker SHALL be cleared when it allows. The pass SHALL stop for a
marker only when it is a `rate_limit` pause.

#### Scenario: A marker older than the reading

- **GIVEN** a usage marker whose end is in the future and a current reading under the threshold
- **WHEN** a unit asks to start
- **THEN** it starts, the marker is cleared, and no refusal is made from the marker's end

#### Scenario: The tick after a cleared pause

- **GIVEN** a usage marker and a guard that allows
- **WHEN** a tick finds nothing ready for another reason
- **THEN** its outcome is not "paused"

### Requirement: A reading is not used past its window

A cached reading, whether within the cache time, kept as the last good reading or taken from the editor, SHALL NOT be used
as the figure of a window it describes after that window's reset. The figure of a window that has not reset MAY still be the base of an estimate.

#### Scenario: The fallback after a reset

- **GIVEN** a failing live call and a good reading, younger than the fallback age, of a window that has since reset
- **WHEN** a unit asks to start
- **THEN** that reading is not used

#### Scenario: One window reset and the other did not

- **GIVEN** a failing live call and a good reading whose session window has since reset and whose weekly window has not
- **WHEN** a unit asks to start
- **THEN** the session figure of that reading is not used, and the weekly figure may be the base of the estimate

### Requirement: A running step is not judged by the threshold

A step that began under the threshold SHALL finish. The threshold SHALL be applied when a start is asked for, so exhaustion
during a run is noticed at the next gate.

#### Scenario: Exhaustion mid-run

- **GIVEN** a step that began under the threshold and a later reading over it
- **WHEN** the step is still running
- **THEN** it is not stopped, and the next start is refused

### Requirement: A rate-limit stop ends at its deadline

A `rate_limit` pause SHALL stop new builds only until its deadline, and the stop SHALL be worked out again each round, not
kept as a flag for the rest of the pass.

#### Scenario: The deadline passes within the pass

- **GIVEN** a pass stopped by a `rate_limit` pause
- **WHEN** the deadline passes and the next round runs
- **THEN** the ready units are submitted

### Requirement: The cache is counted

The usage cache SHALL report its hits, misses, expiries and waits on the refresh lock through the existing telemetry.

#### Scenario: A hit and a miss

- **WHEN** a reading is served from the cache, and later the cache has expired and is refreshed
- **THEN** a hit, an expiry and a miss are counted

### Requirement: A refused or unreadable read does not pause while the reading held leaves ample headroom

When the endpoint cannot be asked or does not answer (a refusal, a cool-down, a timeout, an error, or the minimum interval that
holds a call back) and the guard's own cache holds a last good reading of any age, the guard SHALL estimate each window's usage now
and SHALL allow a start when, in both windows, the estimate plus the headroom margin (`usage_headroom_margin_pct`, five points by
default) is below the threshold that applies to that window at that moment. It SHALL refuse the start, as it does today, when it is not, and when
there is no such reading. The windows are judged separately, each against its own threshold. A reading younger than the fallback age
that covers a failed call is used as read, as before, with no estimate. A reading that shows the plan limit reached, or credits
enabled with a window full, is never the base of an estimate. An actual reading over a threshold SHALL pause exactly as before.

#### Scenario: A refused read with room to spare

- **GIVEN** a last good reading eighty-nine minutes old with the session at 0% against a threshold of 92% and the weekly at 65% against 80%, an endpoint that answered 429 with a retry time of zero, and a cool-down in force
- **WHEN** a unit asks to start
- **THEN** it is allowed on an estimate, no call is made, and the pause that the old rule wrote is not written

#### Scenario: A reading near the threshold

- **GIVEN** the same refusal and a last good reading with the weekly window at 78% against 80%
- **WHEN** a unit asks to start
- **THEN** it is refused as today, because 78 plus the margin is not below 80, and the reason names the estimate

#### Scenario: No reading at all

- **GIVEN** a refused read and no reading kept in the guard's cache, and none the editor holds
- **WHEN** a unit asks to start
- **THEN** it is refused as today, for the unknown-retry interval

#### Scenario: Only the editor's reading

- **GIVEN** a refused read, no reading kept in the guard's cache and a reading in the editor's own cache with ample headroom
- **WHEN** a unit asks to start
- **THEN** the estimate is not made from it and the rule for a stale reading applies as it does today

#### Scenario: An actual reading over the threshold

- **GIVEN** a live reading with the session at 95% against 92%
- **WHEN** a unit asks to start
- **THEN** it is refused and paused until the window's relief, as before, with no estimate made

#### Scenario: A reading that is not old enough to need an estimate

- **GIVEN** a failed live call and a last good reading ten minutes old, younger than the fallback age
- **WHEN** a unit asks to start
- **THEN** that reading is used as read and no estimate is made, as before

#### Scenario: The plan limit is reached

- **GIVEN** a refused read and a kept reading that shows the plan limit reached
- **WHEN** a unit asks to start
- **THEN** it is refused and no estimate is made

#### Scenario: The session and the week judged separately

- **GIVEN** a refused read, a kept reading with the session at 10% against 92% and the weekly at 77% against 80%
- **WHEN** a unit asks to start
- **THEN** it is refused for the weekly window, the reason names the weekly figure, and the session's room does not offset it

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

### Requirement: A fresh reading in Claude Code's own cache is used before the endpoint is asked

Before the guard asks the endpoint, it SHALL read the usage block in Claude Code's own cache (`cachedUsageUtilization` in
`~/.claude.json`) and SHALL decide from it, making no call, when the block was fetched within `usage_claude_cache_minutes`
(by its `fetchedAtMs`, never by the file's modification time), describes both windows, has no window past its reset, and is fresher than the
reading kept in the guard's own cache, a tie going to the guard's own. When both cached readings are fresh the fresher SHALL be used. The
reading SHALL be judged like any other (thresholds, ramp and relief), so a fresh block over a threshold refuses and pauses as an actual
reading does, and a decision from it SHALL be made without a call even when the minimum interval holds the endpoint back. A block that is
older than the window, past a reset, missing, unreadable, torn or malformed SHALL read as absent, silently, and never as zero usage. The
block carries no credits state, so the credits and spend-limit rules SHALL NOT fire on a reading from it.

#### Scenario: A fresh block is used

- **GIVEN** a block fetched six minutes ago with the session at 20% and the weekly at 31%, a window of fifteen minutes, and a reading in the guard's own cache older than the cache time
- **WHEN** a unit asks to start
- **THEN** it is allowed from the block, the endpoint is not called, and the guard's own cache file is not changed

#### Scenario: A block older than the window

- **GIVEN** a block fetched twenty minutes ago and a window of fifteen minutes
- **WHEN** a unit asks to start
- **THEN** the block is not used and the decision is made as it is without the step

#### Scenario: Only the fetch time counts

- **GIVEN** a file modified a minute ago whose block was fetched two days ago
- **WHEN** a unit asks to start
- **THEN** the block is not used

#### Scenario: The block is fresher than the guard's own reading

- **GIVEN** a reading in the guard's own cache nine minutes old and a block six minutes old, both within the window
- **WHEN** a unit asks to start
- **THEN** the block is the reading used

#### Scenario: The block is older than the guard's own reading

- **GIVEN** a reading in the guard's own cache three minutes old and a block six minutes old, both within the window
- **WHEN** a unit asks to start
- **THEN** the guard's own reading is used

#### Scenario: A tie

- **GIVEN** a reading in the guard's own cache and a block observed at the same moment
- **WHEN** a unit asks to start
- **THEN** the guard's own reading is used

#### Scenario: A window in the block has reset

- **GIVEN** a block fetched six minutes ago whose session window reset three minutes ago
- **WHEN** a unit asks to start
- **THEN** the block is not used

#### Scenario: An unreadable block

- **GIVEN** a Claude Code file that is missing, is not valid JSON, is cut off part way, has no usage block, has one window only, or has a fetch time that is not a number
- **WHEN** a unit asks to start
- **THEN** the block reads as absent, nothing is logged for it, no usage is taken as zero, and the decision is made as it is without the step

#### Scenario: A fresh block over a threshold

- **GIVEN** a block fetched six minutes ago with the session at 95% against a threshold of 92%
- **WHEN** a unit asks to start
- **THEN** it is refused and paused until the window's relief, as an actual reading would, and the endpoint is not called

#### Scenario: Inside the minimum interval

- **GIVEN** a call made two minutes ago, so that the minimum interval has not passed, and a fresh block that allows
- **WHEN** a unit asks to start
- **THEN** it is allowed from the block and not refused for the time left to the next permitted call

#### Scenario: The credits rule does not fire

- **GIVEN** a fresh block with the session at 20% and the weekly at 31%
- **WHEN** a unit asks to start
- **THEN** it is decided by the thresholds alone, as a reading from the fallback is

#### Scenario: The status command

- **GIVEN** a fresh block fresher than the reading held in the guard's own cache
- **WHEN** the status command is run without a refresh
- **THEN** it prints the block's reading with its age and source, and makes no call

### Requirement: A reading from Claude Code's own cache is only a reading

A reading taken from Claude Code's own cache for this rule SHALL NOT be written to the guard's own cache, SHALL NOT start a cool-down,
SHALL NOT move the time a reading is kept or the time of the next permitted call, SHALL NOT be the base of an estimate, and SHALL NOT
count as a call to the endpoint in the record's refusal and safe-interval figures. The pipeline SHALL NOT write to Claude Code's file.

#### Scenario: The guard's own cache is untouched

- **GIVEN** a fresh block used for a decision
- **WHEN** the guard's own cache file is read afterwards
- **THEN** it holds what it held before, with no new reading and no cool-down

#### Scenario: The next permitted call

- **GIVEN** a call to the endpoint ten minutes ago and a decision answered from a fresh block one minute ago
- **WHEN** the time of the next permitted call is worked out
- **THEN** it is the same as if no decision had been answered from the block

#### Scenario: A stale block is no base

- **GIVEN** a block older than the window and no reading kept in the guard's own cache
- **WHEN** a unit asks to start with the endpoint refusing
- **THEN** the block is not used to estimate anything and the stale rule applies to it as today

### Requirement: A reading from Claude Code's own cache says where it came from and is counted apart

A decision from the block SHALL say so: the reason and the status command give the source `claude.json` and the block's age, for example
`usage: session 20%/92%, weekly 31%/80% (claude.json, 6m old)`. The call record SHALL gain a line for it with the outcome `claude-json`,
the caller and the block's age, held to the same rules as every other line. The call-rate line SHALL count the share answered from it
separately from the cache's: `usage calls: N in the last hour, K refused, P% from the cache, Q% from claude.json, safe interval S`.

#### Scenario: The label

- **WHEN** a start is decided from a fresh block six minutes old
- **THEN** the reason and the status command end `(claude.json, 6m old)`

#### Scenario: The record

- **WHEN** a start is answered from a fresh block
- **THEN** the record gains a line with the outcome `claude-json`, the caller and the block's age in seconds, and no status code or token

#### Scenario: The rate line

- **GIVEN** in the last hour three calls to the endpoint, four answers from the guard's own cache and five from the block
- **WHEN** the call-rate line is printed
- **THEN** it says 33% from the cache and 42% from claude.json, and the two shares are not added together

### Requirement: The time Claude Code's own cache is trusted is a setting

The time a block in Claude Code's own cache is used for a decision SHALL be `usage_claude_cache_minutes`, which SHALL default to
`usage_cache_minutes`, SHALL be refused when below zero, and SHALL turn the step off when it is zero, so that the read order is as it
was before this requirement. Its effective value SHALL NOT exceed the age past which a cached reading from Claude Code's own cache is
refused as stale.

#### Scenario: The default

- **GIVEN** no value set and `usage_cache_minutes` of fifteen
- **WHEN** the setting is read
- **THEN** it is fifteen minutes

#### Scenario: Zero turns it off

- **GIVEN** a value of zero and a block fetched a minute ago
- **WHEN** a unit asks to start
- **THEN** the block is not used and the order of readings is as before

#### Scenario: A negative value

- **WHEN** the value is below zero
- **THEN** the configuration is refused

#### Scenario: A value above the stale age

- **GIVEN** a value of ninety minutes and a block fetched seventy minutes ago
- **WHEN** a unit asks to start
- **THEN** the block is not used, since it is older than the age after which a reading from Claude Code's own cache is refused as stale

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
