## ADDED Requirements

### Requirement: Every agent call records its own cost and its session's running total

Every agent record SHALL carry one `cost` object holding the call's own spend (`incremental_usd`), the session's running
total as the runtime reported it (`cumulative_usd`), how the incremental figure was obtained (`basis`, one of `reported`,
`derived`, `first`, `unknown`, `backfilled` or `legacy`) and, where a gateway's figure is recorded instead, the runtime's
own incremental figure (`reported_usd`). A record SHALL NOT carry a flat cost figure beside it. For a runtime whose figure
is a running total, `incremental_usd` SHALL be that total minus the session's previous total, with a baseline of 0 for the
session's first call. The previous total SHALL be kept on the recorded session; a resumed call with none recorded SHALL
take the last ledger record with the same session id, and with neither SHALL record `basis` `unknown` and no incremental
figure, never the total. A total lower than the baseline SHALL start a new baseline and be noted. A figure the runtime
does not report SHALL be absent, never zero.

#### Scenario: The first call of a session

- **WHEN** the first call of a session on the Claude Code runtime ends reporting a total of 2.63
- **THEN** its `incremental_usd` is 2.63, its `cumulative_usd` is 2.63 and its `basis` is `first`

#### Scenario: A resumed call

- **GIVEN** a session whose recorded total is 2.63
- **WHEN** a resumed call ends reporting a total of 5.49
- **THEN** its `incremental_usd` is 2.86, its `cumulative_usd` is 5.49 and its `basis` is `derived`

#### Scenario: A session of several calls

- **WHEN** a session makes N calls
- **THEN** the sum of their `incremental_usd` equals the last call's `cumulative_usd`

#### Scenario: A resume with no recorded baseline

- **GIVEN** a resumed call whose session has no baseline in the graph state
- **WHEN** the ledger holds an earlier record with the same session id
- **THEN** that record's `cumulative_usd` is the baseline

#### Scenario: A resume with no baseline anywhere

- **GIVEN** a resumed call with no recorded baseline and no earlier ledger record for its session
- **WHEN** the call ends
- **THEN** its `basis` is `unknown` and its `incremental_usd` is absent, not the runtime's total

#### Scenario: A total that falls

- **GIVEN** a session whose recorded total is 10.00
- **WHEN** a call reports a total of 1.20
- **THEN** it is treated as a new session, its `incremental_usd` is 1.20 and the reset is noted

#### Scenario: An ACP call

- **WHEN** an ACP call ends with an update carrying a cumulative amount
- **THEN** the record carries that amount as `cumulative_usd` and an `incremental_usd` of the difference from the baseline,
  with `basis` `derived` or `first`

#### Scenario: A gateway-attributed call

- **GIVEN** a run whose key's own totals are recorded with source `gateway`
- **WHEN** it is the session's second call
- **THEN** `incremental_usd` is the gateway's figure, `cumulative_usd` is the sum of the session's records so far and
  `reported_usd` is the runtime's own incremental figure

#### Scenario: Wiring the baseline

- **WHEN** a call ends on a session the graph records
- **THEN** the recorded session carries the call's cumulative figure for the next call and drops it with the session

### Requirement: A record without a cost object is read as legacy and never summed as incremental

A ledger line that carries a flat `cost_usd` and no `cost` object SHALL be read with `basis` `legacy`, no incremental or
cumulative figure and the old value kept as `legacy_usd`. A legacy figure SHALL NOT be added to any incremental sum. A
line that carries the object SHALL be read from the object alone.

#### Scenario: An older line

- **GIVEN** a line with `cost_usd: 13.18` and no `cost` object
- **WHEN** the ledger is read
- **THEN** its basis is `legacy`, its incremental figure is absent and 13.18 is kept as its legacy figure

#### Scenario: Both forms in one ledger

- **GIVEN** a legacy line and a line with a `cost` object
- **WHEN** a unit's cost is summed
- **THEN** only the object's `incremental_usd` is in the sum

### Requirement: The ledger's reader adds only incremental figures

When the reader adds a resumed call's figures to the record it resumed, it SHALL add `incremental_usd` and carry the last
call's `cumulative_usd`. It SHALL keep one record per unit, node and round as before.

#### Scenario: A session read back

- **GIVEN** the calls of one session, some resumed under one node and round
- **WHEN** the ledger is read
- **THEN** the sum of the records' `incremental_usd` equals the session's final `cumulative_usd`

### Requirement: A temporary command repairs legacy cost rows once

`abk usage backfill-costs` SHALL be a dry run unless `--apply` is given. For each agent row without a `cost` object it
SHALL group by session id and order by time. For a `claude_code` row with source `reported` it SHALL treat the stored
figure as the cumulative total, set `incremental_usd` to the difference from the session's previous row (the first row's
own figure) and `basis` `backfilled`. For any other row it SHALL treat the stored figure as incremental and set
`cumulative_usd` to the running sum of the session. A session in which a figure falls SHALL be left `unknown` with no
incremental figure and listed. With `--apply` it SHALL write a timestamped copy first, hold the ledger lock, rewrite
atomically and skip any row that has the object. It SHALL print the before and after totals per unit and overall and the
number of rows changed and left unknown. A summary whose unit's detail rows survive SHALL be recomputed by the roll-up; a
summary whose detail is gone SHALL be marked `cumulative_summed` and listed. The command and its documentation SHALL say
it is temporary.

#### Scenario: A dry run

- **WHEN** the command runs without `--apply`
- **THEN** it prints the totals and writes nothing, not even a copy

#### Scenario: Applied

- **WHEN** the command runs with `--apply`
- **THEN** a timestamped copy exists, the ledger is rewritten atomically and the totals printed match the rewritten ledger

#### Scenario: Run twice

- **WHEN** it runs again after `--apply`
- **THEN** it reports no legacy rows and the ledger is unchanged

#### Scenario: A Claude Code session

- **GIVEN** a session whose stored figures are 2.63, 5.49 and 13.18
- **WHEN** the command applies
- **THEN** the increments are 2.63, 2.86 and 7.69 and the final cumulative is 13.18

#### Scenario: ACP and gateway rows

- **GIVEN** rows whose stored figures are per call
- **WHEN** the command applies
- **THEN** their increments are unchanged and each gains a running cumulative

#### Scenario: A session that decreases

- **GIVEN** a session whose stored figure falls between two rows
- **WHEN** the command applies
- **THEN** its rows are left `unknown` with no incremental figure and are listed

#### Scenario: A summary with no detail

- **GIVEN** an archived change whose unit has a summary and no detail rows
- **WHEN** the command applies
- **THEN** the summary is marked `cumulative_summed` and listed, and is not rewritten as if corrected

#### Scenario: A summary with surviving detail

- **GIVEN** a summary and the unit's detail rows
- **WHEN** the command applies
- **THEN** the summary is recomputed from the corrected rows

#### Scenario: An append during the rewrite

- **WHEN** a record is appended while the command applies
- **THEN** it waits for the lock and is in the rewritten ledger

### Requirement: Every agent call records its context window use in tokens

Every agent record SHALL carry one `context` object in tokens: `used_start` (the fill at the step's first request),
`used_end` (the fill at its last request, input plus cache read plus cache creation), `added` (`used_end` minus
`used_start`, never negative), `peak` (the largest fill at any request in the step), `compactions` (how many times the
step compacted), `max` (the model's window size) and `basis` (one of `reported`, `estimated` or `unknown`). A step whose
fill shrank SHALL record an `added` of 0 and a compaction. A compaction SHALL be counted from the runtime's own marker
where it has one, and otherwise from a fall in the fill between consecutive requests larger than the configured share of
the window. A figure the runtime does not give SHALL be absent with `basis` `unknown`, and SHALL NOT fail a run. A step
that ends above the configured share of the window SHALL log a warning and nothing SHALL be scheduled from it.

#### Scenario: Per-request usage on the Claude Code runtime

- **GIVEN** a stream whose requests fill 150k, 170k and 195k tokens
- **WHEN** the call is recorded
- **THEN** `used_start` is 150k, `used_end` and `peak` are 195k and `added` is 45k

#### Scenario: A window from the result

- **GIVEN** a result whose `modelUsage` names a context window for the model
- **WHEN** the call is recorded
- **THEN** `max` is that window and `basis` is `reported`

#### Scenario: A window from the table

- **GIVEN** a result with no window and a configured table that names the model
- **WHEN** the call is recorded
- **THEN** `max` is the table's value

#### Scenario: A compaction

- **GIVEN** requests that fill 150k, 195k and then 80k tokens
- **WHEN** the call is recorded
- **THEN** `compactions` is 1, `added` is 0, `peak` is 195k and `used_end` is 80k

#### Scenario: A compaction marker

- **GIVEN** a stream that carries the runtime's own compaction marker
- **WHEN** the call is recorded
- **THEN** the marker is counted instead of the drop in the fill

#### Scenario: An ACP update

- **WHEN** an ACP call receives updates carrying `used` and `size`
- **THEN** `used_end` is the last `used` and `max` is its `size`

#### Scenario: Nothing reported

- **WHEN** a call yields no per-request usage and no window
- **THEN** the context figures are absent, `basis` is `unknown` and the run is unaffected

#### Scenario: Near the limit

- **GIVEN** a configured warning share of 0.8
- **WHEN** a step ends at 170k of 200k
- **THEN** one warning is logged and no scheduling decision changes
