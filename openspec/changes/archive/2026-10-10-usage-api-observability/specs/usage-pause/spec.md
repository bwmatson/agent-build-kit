## ADDED Requirements

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
SHALL respect the retry time a refusal names when it is longer, and SHALL halve after the same time without a refusal, never
below the configured value. The status command SHALL say the interval in use and what set it.

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
