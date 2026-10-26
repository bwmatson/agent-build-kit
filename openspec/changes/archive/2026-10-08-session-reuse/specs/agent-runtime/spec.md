## ADDED Requirements

### Requirement: One entry point runs an agent, and the model is chosen per call

Every node that runs an agent for the build SHALL do so through one `run` entry point, which
takes the model for the call. Choosing the model SHALL NOT depend on which of several
entry points a node calls.

#### Scenario: Two nodes, two models

- **WHEN** `fix_checks` and `rework` each run
- **THEN** both go through `run`, each with the model chosen for it

### Requirement: A continued session may be given a new prompt

A request to continue a session SHALL be able to carry the prompt to send into it. An
interrupted node's request SHALL carry the interruption prompt, as before, and a node
continuing another node's session SHALL carry its own.

#### Scenario: Same session, different message

- **GIVEN** a recorded session
- **WHEN** a request continues it with a prompt
- **THEN** that prompt is sent, not the interruption prompt

### Requirement: An ACP agent's session is resumed only when it is advertised and present

The ACP runtime SHALL read at initialize whether the agent advertises `session/resume` and
`session/list`, and SHALL resume only an agent advertising both. Before resuming, it SHALL
list the sessions for the working directory, following the cursor until the id is found or
the pages end. It SHALL resume with `session/resume` when the id is listed, and otherwise
SHALL open a new session, reporting the session as not continued. It SHALL NOT use
`session/load`. An agent that does not advertise both SHALL be given a new session and no
error.

#### Scenario: The session is listed

- **GIVEN** an agent advertising both capabilities and a listed session id
- **WHEN** a node resumes it
- **THEN** `session/resume` is called with that id and no new session is opened

#### Scenario: The session is not listed

- **GIVEN** an id the agent does not list
- **WHEN** a node resumes it
- **THEN** a new session is opened and the node gets its full prompt

#### Scenario: An agent without the capabilities

- **GIVEN** an agent advertising neither
- **WHEN** a node would continue a session
- **THEN** a new session is opened and the node gets its full prompt, with no error

#### Scenario: The id is on a later page

- **GIVEN** a listing in several pages with the id on the second
- **WHEN** a node resumes it
- **THEN** the cursor is followed and the session is resumed
