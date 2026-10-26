## ADDED Requirements

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

- **GIVEN** the only reading is six hours old
- **WHEN** a unit asks to start
- **THEN** it is refused for the stale-retry interval, the reason says the reading is stale, and the next round asks
  again

#### Scenario: A reading served from the cache file

- **GIVEN** a reading kept in the cache file
- **WHEN** a unit asks to start
- **THEN** the reading's source says it came from the cache, not that it is live, and the staleness test applies to it

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
reading while it is younger than the fallback age, and only then the editor's cached reading. The reason a start
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

- **GIVEN** a failing live call, no good live reading within the fallback age and an old editor reading
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
after the reset of a window it describes.

#### Scenario: The fallback after a reset

- **GIVEN** a failing live call and a good reading, younger than the fallback age, of a window that has since reset
- **WHEN** a unit asks to start
- **THEN** that reading is not used

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
