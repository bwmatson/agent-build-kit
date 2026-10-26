## ADDED Requirements

### Requirement: A live session is streamed, not taken over

While a unit's agent step is running, the UI SHALL stream what the agent is doing and SHALL NOT
accept input to that session.

#### Scenario: A running step

- **GIVEN** a unit with an agent step in progress
- **WHEN** its agent tab is open
- **THEN** messages, tool calls and results appear as they happen and the composer is disabled with
  the reason

### Requirement: A paused session accepts turns under a lease

When a unit's step has ended, the UI SHALL accept a turn to the unit's session. The first turn SHALL
take the lease the tick respects, so no step starts on the unit while it is held, and releasing the
lease, or closing the page, SHALL return the unit to the tick, which resumes from the recorded node.

#### Scenario: Chatting with a unit in review

- **GIVEN** a unit in review and its recorded session
- **WHEN** a turn is sent
- **THEN** it goes to that session, the unit shows that it is attached, and a tick does not start a
  step on it

#### Scenario: Release

- **WHEN** the lease is released
- **THEN** the next tick resumes the unit from its recorded node

#### Scenario: The page closes

- **WHEN** the page holding the lease closes
- **THEN** the lease is released

### Requirement: A new session can be started

The UI SHALL start a new session for a unit, in its worktree, or for a repo, choosing the runtime and
model, and the session SHALL be one the editor's session list also shows.

#### Scenario: A session for a unit

- **WHEN** a new session is started from a unit's page
- **THEN** it starts in the unit's worktree under the lease

### Requirement: A session an editor is driving is read-only

The UI SHALL show a session another process is driving read-only, SHALL refuse input to it while that
process is live, and SHALL offer to continue it as a new session forked from it.

#### Scenario: The editor holds the session

- **GIVEN** a session whose id is held by a running editor process
- **WHEN** it is opened
- **THEN** its history is shown, the composer is disabled, and "fork and continue" is offered

#### Scenario: Forking

- **WHEN** fork and continue is chosen
- **THEN** a new session starts with the history of the first, and the first is not written to

### Requirement: A turn's permission requests are answered in the browser

A permission request from a turn SHALL be shown in the browser and wait for an answer; closing the
page SHALL deny it. A turn SHALL NOT widen the tools the unit is allowed.

#### Scenario: A request

- **WHEN** an agent asks permission for a command during a turn
- **THEN** the request is shown with its options and the turn waits

#### Scenario: The page closes while waiting

- **WHEN** the page closes with a request outstanding
- **THEN** the request is denied

### Requirement: A selection can be sent to the agent as context

A turn SHALL be able to carry attachments, each a file, a line range, the diff hunk and the selected
text, and the prompt sent to the agent SHALL contain them. The composer SHALL show each attachment as a
chip that can be removed before sending.

#### Scenario: A selection from the diff

- **GIVEN** lines selected in a unit's diff
- **WHEN** the user chooses to ask the agent about them
- **THEN** the next turn's prompt contains the file, the lines, the hunk and the text, and the composer
  shows one chip for them

#### Scenario: Removing a chip

- **WHEN** a chip is removed before sending
- **THEN** the prompt does not contain that attachment

### Requirement: A session started elsewhere can be continued here

A session started in an editor, a command line or another agent front end SHALL be listed on the
sessions page and SHALL be continued in place when no process holds it, by resuming its id for a
Claude session and by loading it for an ACP session whose agent can load it. When a process holds it,
the session SHALL be continued as a fork. A session the agent cannot load SHALL be shown read-only
from the history the agent keeps and SHALL be continued as a new session seeded with that history,
and the page SHALL say so.

#### Scenario: An idle Claude session

- **GIVEN** a Claude session started in an editor that no process holds
- **WHEN** it is continued from the sessions page
- **THEN** its id is resumed and the next turn goes into it

#### Scenario: A session an editor still holds

- **GIVEN** a session held by a running editor process
- **WHEN** it is continued
- **THEN** a fork is started and the original is not written to

#### Scenario: A session the agent cannot load

- **GIVEN** an ACP agent session the agent does not offer to load
- **WHEN** it is opened
- **THEN** its history is shown read-only, the page says it can only be continued as a new session,
  and choosing that seeds the new session with the history
