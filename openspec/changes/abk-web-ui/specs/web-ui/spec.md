## ADDED Requirements

### Requirement: A local server shows the pipeline

`abk serve` SHALL run a server bound to the loopback address only, serving a read API and a web UI
over the unit store, the usage ledger, the run logs and the checkpoint store. It SHALL NOT write to
any of them through a read endpoint.

#### Scenario: The server starts

- **WHEN** `abk serve` is run in a planning repository
- **THEN** it listens on the loopback address only and serves the overview page

#### Scenario: A read does not change state

- **WHEN** any read endpoint is called while the pipeline is running
- **THEN** no unit, ledger, log or checkpoint record is changed

### Requirement: A unit has a page under its own name

A unit SHALL be addressed as `change/N` in every URL and API path. Its page SHALL show its effective
state, its cause and note, its history as a timeline of state, time, cause and note, its branch,
base and pull request, its dependencies and merge gates with their states, and its review round.

#### Scenario: Opening a unit

- **WHEN** the page for `needs-gate-started-units/1` is opened
- **THEN** its address contains `needs-gate-started-units/1` and no other identifier

#### Scenario: A held unit

- **GIVEN** a unit held by the review loop
- **WHEN** its page is read
- **THEN** it shows the held state, the recorded cause and who held it, from the record and not from
  the wording of a note

### Requirement: A unit's logs are shown whole and live

A unit page SHALL show its run logs, grouped by node, with the agent's words and tool commands in
full, and SHALL follow a run that is still writing until its outcome line appears.

#### Scenario: A long reply

- **GIVEN** a run log whose agent reply was longer than a line
- **WHEN** the logs are shown
- **THEN** the whole reply is shown, not a clipped line

#### Scenario: A live run

- **GIVEN** a run with no outcome line
- **WHEN** it appends lines
- **THEN** they appear without reloading the page

#### Scenario: An old log

- **GIVEN** a log written before replies were kept whole
- **WHEN** it is shown
- **THEN** it parses, and clipped lines are shown as they were written

### Requirement: Usage on the page is the report's

Usage on a unit's page and on the usage page SHALL come from the same builder as `abk report`, for
the same groupings and filters.

#### Scenario: The same figures

- **WHEN** the usage for a unit is shown and `abk report` is run for it
- **THEN** the totals for every grouping are equal

### Requirement: The metrics page lists every metric from the best source

The metrics page SHALL list every metric the pipeline exports, from a catalogue generated from the
instruments the code defines, with its type and attributes and a chart, SHALL use Prometheus and
Tempo when they answer and local files otherwise, and SHALL show which it used.

#### Scenario: The stores are up

- **GIVEN** Prometheus and Tempo answer
- **WHEN** the page is opened
- **THEN** the charts come from them and the page says so

#### Scenario: The stores are down

- **GIVEN** neither answers
- **WHEN** the page is opened
- **THEN** the charts are derived from local files and the page says so

#### Scenario: A new instrument

- **WHEN** an instrument is added to the telemetry module
- **THEN** the page lists it without a separate edit

### Requirement: Actions go through the CLI's code

Requeue, hold, release and approve from the UI SHALL call the same functions as the CLI, under the
unit store's lock, SHALL be recorded in the log with the actor, and SHALL be refused with the CLI's
reason when the CLI would refuse.

#### Scenario: Requeue a failed unit

- **WHEN** requeue is chosen for a failed unit
- **THEN** the unit is requeued as `abk requeue` would, and the log names the UI as the actor

#### Scenario: A running unit

- **WHEN** an action is chosen for a unit that is running
- **THEN** it is disabled with the reason the CLI gives

### Requirement: Approve records the person's approval and does nothing else

Approving a unit SHALL be one function, `approve_unit`, called by both the UI action and
`abk approve <unit>`. It SHALL record a decision of `approved` for the unit's current review round in
the review store, together with the head commit of the unit's pull request at that moment. It SHALL
NOT merge, push or vote on the host, and SHALL be refused with a reason for a unit with no pull request
or no head, and for a round that already has a decision. `abk approve` SHALL print what it recorded.

#### Scenario: Approve from the UI and from the command line

- **GIVEN** a unit in review with a pull request
- **WHEN** it is approved from its page, and the same on another unit with `abk approve <unit>`
- **THEN** each records an `approved` decision for the round at the head it had then, through the
  same function, and merges nothing

#### Scenario: Nothing to approve

- **GIVEN** a unit with no pull request or no head
- **WHEN** approve is chosen or `abk approve <unit>` is run
- **THEN** it is refused with the reason, in the UI as a disabled action and on the command line as a
  message with a failing exit status, and nothing is recorded

#### Scenario: The command says what it did

- **WHEN** `abk approve <unit>` succeeds
- **THEN** it prints the unit, the head commit and the round the approval was recorded for
