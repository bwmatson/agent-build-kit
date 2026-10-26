# usage-accounting Specification

## Purpose
Records where a unit's tokens and time are spent, by node, round and session, so the
cost of a build can be analysed and the places worth improving found.

## Requirements

### Requirement: Every agent call's reported usage is recorded with its unit

For each agent call the pipeline SHALL record the tokens by kind (input, output,
cache read, cache write), cost, turns, duration and session id the runtime
reports, together with the unit, change, repository, node, review round, role,
model and runtime, in an append-only ledger in the state directory. Each figure
SHALL carry its source (reported, estimated or none). A figure the runtime does not
report SHALL be recorded as absent and never as zero, and an estimate SHALL be
flagged and kept apart from measured figures. Recording SHALL NOT affect a run: a
failed write SHALL be dropped and reported once.

#### Scenario: A call on the Claude runtime

- **WHEN** a unit's review round completes on the Claude runtime
- **THEN** one record names the unit, node, round, role and model, carries the
  reported tokens, cost, turns and duration, and has source `reported`

#### Scenario: A runtime that reports nothing

- **WHEN** an ACP agent returns no usage
- **THEN** the record's figures are absent and its source is `none`, or its tokens
  are estimates flagged as such

#### Scenario: The ledger cannot be written

- **GIVEN** a state directory that cannot be written
- **WHEN** an agent call completes
- **THEN** the run continues unchanged and one line reports the failure

### Requirement: A resumed or re-run call is counted once

A node re-run after a kill SHALL NOT double count: the ledger's reader SHALL keep one record
per unit, node, round and call. A call that continues a session another node started, as
`fix_checks` continuing the build session does, SHALL be counted under the node that made
the call, and the session id SHALL be an attribute of the record, not part of its key, so one
session id may appear under several nodes. A record of a node outside the unit graph's call nodes
(`tests`, `implement`, `review`, `rework`, `fix_checks`, `adapt`) is a call of its own, never a re-run
of another and never added to one, whatever its session id, so two such calls for one unit, or a call
with no unit, are two records.

#### Scenario: A node killed and re-run

- **GIVEN** a node whose call was recorded and which then ran again
- **WHEN** the ledger is read
- **THEN** that node and round count once

#### Scenario: A fix continuing the build session

- **GIVEN** `implement` and then `fix_checks` in one session
- **WHEN** the ledger is read
- **THEN** each node's spend is under its own node, and both records carry the session id

#### Scenario: Two resolver calls for one unit

- **GIVEN** two `restack` rows for the same unit, written at different times, one of them in a session the other started
- **WHEN** the ledger is read
- **THEN** both are records and the unit's `restack` spend is their sum

#### Scenario: Calls with no unit

- **GIVEN** two `plan` rows and three `chat` turns of one session, none with a unit
- **WHEN** the ledger is read
- **THEN** each is its own record, and none replaces or is added to another

### Requirement: A change in the ACP payload cannot fail a run

The ACP runtime SHALL parse usage tolerantly, record whether the agent offers it, and
on a payload it cannot parse fall back to the next source and log once. A contract
test SHALL replay recorded payloads with and without usage and with an extra field.

#### Scenario: An unknown field

- **WHEN** a usage payload carries a field the runtime does not know
- **THEN** the known figures are recorded and the run is unaffected

### Requirement: A gateway-backed agent run is attributed from the gateway's own records

When a gateway is configured and the runtime reaches its model through it, the
framework SHALL give each agent run a key of its own whose alias names the unit,
node and round, SHALL read that key's token and cost totals afterwards, SHALL record
them with source `gateway`, and SHALL revoke the key. Where no gateway is configured,
or the agent cannot take its key from its environment, the source SHALL be skipped
with a log line and the record SHALL fall back to the next source. A gateway failure
SHALL NOT fail a run.

#### Scenario: A run through the gateway

- **GIVEN** a configured gateway and an agent that takes its key from the environment
- **WHEN** a unit's implement step runs
- **THEN** the gateway's totals for that run's key are recorded with source `gateway`
- **AND** the key is revoked afterwards

#### Scenario: Concurrent units

- **WHEN** two units run agents at the same time
- **THEN** each unit's record holds only its own key's totals

#### Scenario: No gateway configured

- **WHEN** neither gateway setting is set
- **THEN** no key is minted and records use their other sources

#### Scenario: The gateway is down

- **GIVEN** a configured gateway that does not answer
- **WHEN** an agent run starts
- **THEN** the run proceeds, the record falls back and one warning is logged

### Requirement: A unit's time is recorded as durations by kind

The pipeline SHALL record, in the accounting ledger, the start, end and duration of
each node a unit runs, the time a ready unit waits for a slot, the time it is paused
for the usage window, and the duration of each unit-test command, all with UTC stamps
and the unit, change, node, round and a wait bucket. Time a pull request waits in
review SHALL be derivable from the unit's state history. Recording SHALL NOT affect
a run.

#### Scenario: A unit waits for a slot

- **GIVEN** more ready units than free slots
- **WHEN** a unit is submitted and later starts
- **THEN** a record carries the time between, with bucket `slot`

#### Scenario: A usage pause between steps

- **WHEN** the usage guard interrupts a unit before an agent step and a later tick
  resumes it
- **THEN** a record carries the time between, with bucket `usage_pause`

#### Scenario: A node that raises

- **WHEN** a node raises
- **THEN** its span is still recorded, with the failure outcome

#### Scenario: Unit-test

- **WHEN** a unit's unit-test command runs for 45 seconds
- **THEN** a record carries that duration under its command

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

### Requirement: A wait is one span carrying its reason

A stretch a unit spends not running SHALL be recorded as a single span whose `waited` field names its reason and which names no node, for every reason in the defined set, and no stretch SHALL be recorded both as a wait and as a node. A review round SHALL be recorded as a span with a cause of review, check or conflict, a conflict being the rework a restack started. A usage-paused unit SHALL display as paused without a new stored state.

#### Scenario: A wait recorded once

- **WHEN** a unit waits for a slot and later starts
- **THEN** one span carries `waited` of `slot` and the wait metric counts it once

#### Scenario: A rework from a restack

- **WHEN** a restack sends a unit back for rework
- **THEN** its round's span has the cause conflict

#### Scenario: A paused unit

- **WHEN** a unit is parked on a usage pause
- **THEN** it displays as paused and its stored state is unchanged

### Requirement: A unit's summary holds all its wait figures

When a change is archived, each unit's summary SHALL carry `slot_wait_ms`, `pause_wait_ms` and `review_wait_ms`, review being split into a person's, rounds' and checks'. A summary written before this SHALL still load.

#### Scenario: Archiving

- **WHEN** a change is archived
- **THEN** every unit's summary has the three figures, none null for a unit that had the wait

#### Scenario: An older summary

- **WHEN** the ledger holds a summary with null wait figures
- **THEN** it loads and reads as absent

### Requirement: Every agent call writes exactly one ledger row

On every path a call can take, new, resumed or continued, under every runtime, an agent call SHALL write exactly one ledger row. This holds for every call that sends a prompt to an agent, not only
the unit graph's steps: a call outside the unit graph SHALL be recorded under its own node name by the shared helper.

#### Scenario: Each path

- **WHEN** a call is made on each path
- **THEN** one row exists per call

#### Scenario: A call outside the unit graph

- **WHEN** the conflict resolver, the planner, a track run, init's research or proposal, the policy probe, the login refresh or a chat turn makes a call
- **THEN** one row exists for it, with the node `restack`, `plan`, `track_<phase>`, `init_research`, `init_propose`, `policy_probe`, `login_refresh` or `chat`

### Requirement: A call outside the unit graph is recorded under its own node

An agent call made by the framework outside a unit's graph SHALL write a ledger row with the schema every row has, under the node named for
the call: `restack` for the conflict resolver, `plan` for the planner, `track_health`, `track_improve`, `track_recommend` and `track_propose`
for a track phase, `init_research` and `init_propose` for init's runs, `policy_probe` for the policy probe, `login_refresh` for the
login refresh, `chat` for a chat turn and `chat_commit` for the attach flow's fix turn. The row SHALL be built by one helper that the unit steps also use, so
cost, its cumulative baseline, tokens, context, turns, duration, session and source are worked out in one place. `unit` SHALL be blank
where the call has none, and `change` and `repo` SHALL be filled when the caller knows them. `role` SHALL be the request's role,
`generic` where the call has none of the roles the `models` settings choose a model for, and `model` the model the request names, absent when the runtime
chooses. A figure the call does not report SHALL be absent, never zero. A call that fails SHALL write its row with outcome `failed`. A write that fails SHALL be dropped and reported
once and SHALL NOT affect the call.
The usage estimate counts a row by its `cost.incremental_usd`, with a unit or without one: a row with no cost, as the login refresh writes, and a call killed
before it delivered a result, which writes no row, add nothing to the estimate.

#### Scenario: A row for a call with no unit

- **WHEN** the planner makes a call that reports tokens and cost
- **THEN** one row exists with node `plan`, a blank unit, the reported tokens and cost, source `reported` and outcome `ok`

#### Scenario: A failed call

- **WHEN** a track phase's agent returns an error
- **THEN** its row has outcome `failed` and the figures the runtime reported

#### Scenario: A runtime that reports nothing

- **WHEN** the login refresh discards the agent's output
- **THEN** its row has source `none`, no tokens and no cost, a duration, and outcome from the exit status

#### Scenario: The unit steps are unchanged

- **GIVEN** the same results from a unit's `implement`, `review` and `fix_checks` steps
- **WHEN** they are recorded through the helper
- **THEN** the rows are identical to those written before the helper existed

#### Scenario: A secret in a free-text field

- **WHEN** a row of a new node is written
- **THEN** its identifying fields are kept as written and a secret in `outcome` or any other text field is withheld

#### Scenario: A usage estimate

- **GIVEN** rows with a blank unit, one of them a `plan` row with a cost, and a row for a unit since a reading
- **WHEN** the usage estimate and its calibration count the units that spent
- **THEN** the blank unit is not counted as a unit and the unit is, and on the `cost` basis the `plan` row's cost is counted with the unit's

#### Scenario: A row with no cost

- **GIVEN** a `login_refresh` row with a duration and no cost
- **WHEN** the usage estimate counts the cost recorded since a reading
- **THEN** the row adds nothing and does not make a unit

### Requirement: The conflict resolver is recorded as the restack node

Each call the conflict resolver makes SHALL write one row with node `restack`, the unit being moved as `unit`, its model, tokens, cost, context, turns and
duration, one row per call. A resolver that is refused for the usage limit, or
that fails, SHALL write its row before the refusal or failure is raised. A restack that finds no conflict makes no call and SHALL write no row.

#### Scenario: A conflict resolved

- **WHEN** a restack conflicts and the resolver runs once
- **THEN** one `restack` row names the unit being moved and carries the resolver's cost, tokens, duration and model

#### Scenario: Two conflicts for one unit

- **WHEN** a unit's restack conflicts and later conflicts again
- **THEN** there are two `restack` rows for it, and the unit's `restack` spend is their sum

#### Scenario: A clean restack

- **WHEN** a restack applies cleanly
- **THEN** no `restack` row is written

#### Scenario: A resolver refused

- **WHEN** the resolver's run is refused for the usage limit
- **THEN** its row is written with outcome `failed` and the refusal is still raised

### Requirement: A new call that records nothing fails unit-test

A guard test SHALL find every construction of an agent request and every direct run on a runtime in the source and fail naming the file and line of each that does not record, unless
it is on an allowlist whose every entry has a reason. A request that sets only `on_record`, which writes transcript events and no ledger row, SHALL NOT pass. The allowlist SHALL only shrink: an entry
whose site now records, or whose site is gone, SHALL fail the test until it is removed. A call that sends a prompt through a command line, as the login refresh does, SHALL be found too.

#### Scenario: An unrecorded construction

- **WHEN** a source file constructs an agent request with neither `on_result` nor a recording wrapper and is not allowlisted
- **THEN** the guard fails naming the file and line

#### Scenario: A transcript is not a row

- **WHEN** a request sets `on_record` and no `on_result`
- **THEN** the guard fails

#### Scenario: A recorded site

- **WHEN** a request is built through the helper or sets `on_result`
- **THEN** the guard passes it

#### Scenario: An allowlisted site

- **WHEN** a site is on the allowlist with a reason
- **THEN** the guard passes it

#### Scenario: A stale entry

- **WHEN** an allowlisted site now records or no longer exists
- **THEN** the guard fails until the entry is removed

#### Scenario: A run that is not an agent's

- **WHEN** the source calls `subprocess.run` or `asyncio.run`
- **THEN** the guard leaves it alone

#### Scenario: An unknown node name

- **WHEN** a site records under a node name that is not in the closed set
- **THEN** the guard fails

#### Scenario: Nothing allowlisted at the end

- **WHEN** this change is complete
- **THEN** the allowlist is empty

### Requirement: Chat turns are recorded

Each turn of a chat session SHALL write one row with node `chat`, the attach flow's fix turn one row with node `chat_commit`. A turn that resumes
a session SHALL record its own incremental cost, as any resumed call does. A session attached to a unit SHALL carry that unit, its change and its repository,
and any other session a blank unit. Recording SHALL NOT change the transcript the chat keeps or the events it streams.

#### Scenario: A turn on an attached session

- **WHEN** a person sends a message in a session attached to a unit
- **THEN** one `chat` row exists with that unit and the turn's tokens and cost

#### Scenario: A second turn

- **WHEN** the same session takes a second turn
- **THEN** a second row exists whose incremental cost is the turn's own

#### Scenario: A session with no unit

- **WHEN** a person chats in a session attached to no unit
- **THEN** its rows have a blank unit and the usage estimate counts no unit for them

### Requirement: A unit's forecast and each step admitted are recorded when the guard admits them

When the guard admits a unit's first agent step it SHALL append to `usage-forecasts.jsonl` in the state directory a forecast row with the
unit, its review tier and size band, the time, the forecast of each window in dollars and points, the dollars by role and node, and
whether the unit's history or the prior was used; and for every agent step it admits, a step row with the unit, node, round and time.
Rows SHALL be appended once however many times the same ask is repeated, SHALL be written under the lock the ledger uses, and a failure
to write one SHALL be logged and SHALL NOT refuse or fail the start. A line that cannot be parsed SHALL be skipped by every reader. With
`usage_forecast` off no row SHALL be written. These rows are not ledger rows and are never added to a cost.

#### Scenario: A unit's first step

- **GIVEN** a unit with no forecast row that is admitted
- **WHEN** the admission is recorded
- **THEN** one forecast row holds its tier, band, forecast per window in dollars and points, dollars by role and node, and whether the prior was used, and one step row holds its node, round and time

#### Scenario: A later step

- **GIVEN** a unit with a forecast row that is admitted to its next step
- **WHEN** the admission is recorded
- **THEN** a step row is appended and no second forecast row

#### Scenario: The same ask twice

- **GIVEN** a unit admitted at a gate that is asked again for the same step on the same reading
- **WHEN** the admission is recorded
- **THEN** one step row exists for it

#### Scenario: A write that fails

- **GIVEN** a state directory the record cannot be written in
- **WHEN** a unit is admitted
- **THEN** a line says so, the unit is admitted and no error is raised

#### Scenario: A half-written line

- **GIVEN** a record whose last line is cut off
- **WHEN** it is read
- **THEN** the line is skipped and the others are read

#### Scenario: Forecast off

- **GIVEN** `usage_forecast` false
- **WHEN** a unit is admitted
- **THEN** no row is written
