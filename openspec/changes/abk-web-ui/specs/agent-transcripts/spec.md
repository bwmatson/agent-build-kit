## ADDED Requirements

### Requirement: Every agent interaction is recorded whole

Each agent run, and each chat turn made through the server, SHALL be recorded as it streams to a
transcript for its unit, one event per line, with the time, the unit, the node and round, the session
id, the source (build or chat) and the kind of event: text, reasoning, tool call, tool result, plan,
usage, permission or stop. Content SHALL be kept whole, except that a tool result longer than the
configured size is cut with a marker saying so. The record SHALL be the same for the Claude and the
ACP runtime.

#### Scenario: A Claude step

- **WHEN** a step runs on the Claude runtime
- **THEN** its text, reasoning, tool calls and results, usage and stop are written to the unit's
  transcript as they arrive, with the session id

#### Scenario: An ACP step

- **WHEN** a step runs on the ACP runtime
- **THEN** the same kinds of event are written in the same shape, including tool calls the agent's own
  session history would not replay

#### Scenario: A very large tool result

- **GIVEN** a tool result longer than the configured size
- **WHEN** it is recorded
- **THEN** it is cut at that size and ends with a marker giving the original length

#### Scenario: A chat turn

- **WHEN** a turn is made through the server
- **THEN** it is recorded with the source marked as chat, in the same transcript sequence

### Requirement: The agent tab replays the recorded history

The agent tab SHALL show a unit's history from its transcripts, across build runs and chat turns, with
tool calls and results, and SHALL show a session that was not recorded from the history its runtime
keeps, saying where tool calls are not available.

#### Scenario: A unit built and then chatted with

- **GIVEN** a unit with build runs and a chat turn
- **WHEN** its agent tab is opened
- **THEN** it shows all of them in order, tool calls included

#### Scenario: A session abk did not record

- **GIVEN** a session started in an editor
- **WHEN** it is opened
- **THEN** its history is read from the runtime's own record, and the page says if tool calls are not
  available from it

### Requirement: Transcripts are bounded and local

Transcripts SHALL be kept for the most recent runs of each unit, up to a configured number, SHALL be
removed with the unit's run logs when its change is archived, and SHALL NOT leave the machine.

#### Scenario: More runs than are kept

- **GIVEN** a unit with more runs than the configured number
- **WHEN** a new run starts
- **THEN** the oldest transcript is removed

#### Scenario: Archive

- **WHEN** a change is archived
- **THEN** its units' transcripts are removed with their run logs
