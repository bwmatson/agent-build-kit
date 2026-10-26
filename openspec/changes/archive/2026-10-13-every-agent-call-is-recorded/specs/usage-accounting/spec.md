# usage-accounting delta

## MODIFIED Requirements

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

### Requirement: Every agent call writes exactly one ledger row

On every path a call can take, new, resumed or continued, under every runtime, an agent call SHALL write exactly one ledger row. This holds for every call that sends a prompt to an agent, not only
the unit graph's steps: a call outside the unit graph SHALL be recorded under its own node name by the shared helper.

#### Scenario: Each path

- **WHEN** a call is made on each path
- **THEN** one row exists per call

#### Scenario: A call outside the unit graph

- **WHEN** the conflict resolver, the planner, a track run, init's research or proposal, the policy probe, the login refresh or a chat turn makes a call
- **THEN** one row exists for it, with the node `restack`, `plan`, `track_<phase>`, `init_research`, `init_propose`, `policy_probe`, `login_refresh` or `chat`

## ADDED Requirements

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

- **GIVEN** rows with a blank unit and a row for a unit since a reading
- **WHEN** the usage estimate and its calibration count the units that spent
- **THEN** the blank unit is not counted as a unit and the unit is

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

### Requirement: A new call that records nothing fails tier 1

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
