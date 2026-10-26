## ADDED Requirements

### Requirement: The usage endpoint is asked only when a fresh reading could change a decision

For a decision to start work or to resume paused work, the guard SHALL use the reading it holds when that
reading settles the decision, and SHALL ask the endpoint only when a fresh reading could change it. A refusal made on a reading of
a window that has not reset SHALL stand without a call, an allowance SHALL stand while the usage could not have reached the
threshold since the reading, and a reading of a window that has reset SHALL not be used.

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
interval it SHALL refuse the start for the time left to the next permitted call, with a reason that says so, and not make a call.

#### Scenario: A decision that needs a reading too soon

- **GIVEN** a call made two minutes ago and a decision close to the threshold
- **WHEN** a unit asks to start
- **THEN** it is refused for the time left to the next permitted call, and the endpoint is not called

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
