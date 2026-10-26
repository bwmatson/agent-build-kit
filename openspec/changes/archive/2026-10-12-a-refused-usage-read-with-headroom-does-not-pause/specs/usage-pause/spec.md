## MODIFIED Requirements

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

## ADDED Requirements

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

The estimate of a window SHALL be the reading's figure for that window plus, for each unit that has spent since the reading or been
admitted on an estimate since the reading, a flat allowance of points for that window
(`usage_unit_allowance_pct` on each window's settings, ten points for the session window and two for the weekly by default). A unit
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

### Requirement: A window that has reset since the reading is estimated from its reset

A window whose reset time lies between the reading's time and now SHALL NOT take the reading's figure. Its estimate SHALL start at
zero at the reset, add the most that could have been added since the reset (the fastest climb seen for that window, no slower than
the configured floor, with its margin), and add the allowance for each unit that has spent or been admitted since the reset. A
window the reading says is not open SHALL start from its figure, which is zero.

#### Scenario: The session window has reset

- **GIVEN** a kept reading from before the session window's reset, with the session at 88%, the reset forty minutes ago and the weekly window not reset
- **WHEN** a unit asks to start with the read refused
- **THEN** the session estimate starts from the reset, not from 88%, and the weekly estimate from its reading

#### Scenario: The reset was long ago

- **GIVEN** a session window that reset ten hours ago, a climb floor of 0.2 points a minute and a margin of 2
- **WHEN** the session estimate is made
- **THEN** it is 122 points and the start is refused for the session, since no estimate could be trusted that far from a reading

### Requirement: Starts on an estimate are capped per reading

The guard SHALL admit at most `usage_estimate_max_starts` units (three by default) on an estimate for one reading; the count SHALL be
kept with the reading in the cache and start again from zero when a good reading is taken. A start refused by the cap
SHALL be refused until the next permitted call, with a reason that says the cap was reached.

#### Scenario: The cap is reached

- **GIVEN** a cap of three, a kept reading with ample headroom and three units admitted on an estimate since it
- **WHEN** a fourth unit asks to start with the read refused
- **THEN** it is refused until the time the endpoint may next be asked, and the reason says three starts have been made on an estimate

#### Scenario: A good reading resets the count

- **GIVEN** three units admitted on an estimate and then a good live reading
- **WHEN** a unit asks to start
- **THEN** it is decided from the new reading, and the count is zero

### Requirement: A start on an estimate says so

A decision to start on an estimate SHALL carry a reason that gives the reading's age, each window's estimate with the figure read and the
points added, and that starts are being allowed, for example `usage: reading 89m old, session ~15% estimated (0% read + 15% spent),
weekly ~71% estimated (65% read + 6% spent), allowing starts`. A refusal that rests on an estimate SHALL say so in the same terms. The
status command SHALL print the same line, without a call, whenever the reading it holds is older than the time a reading is kept and
the endpoint cannot be asked.

#### Scenario: The reason of an allowance

- **WHEN** a start is allowed on an estimate
- **THEN** the reason shows the reading's age, the estimate of each window with the figure read and the points added, and the threshold each is judged against

#### Scenario: The status command

- **GIVEN** a held reading older than the time a reading is kept and a cool-down in force
- **WHEN** the status command is run
- **THEN** it prints the estimate line, makes no call, and still prints the held reading and its age
