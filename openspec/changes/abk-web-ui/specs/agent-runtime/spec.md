## ADDED Requirements

### Requirement: An ACP session is recorded and can be resumed

The ACP runtime SHALL record the session id when a session starts, as the Claude runtime does, and
SHALL resume a session when the agent declares it can load one. When the agent cannot, a resume
SHALL start a new session and say so.

#### Scenario: A session starts

- **WHEN** an ACP step starts a session
- **THEN** its id is recorded for the unit and node

#### Scenario: A resume with an agent that can load sessions

- **GIVEN** an agent that declares session loading and a recorded session
- **WHEN** the unit's step resumes
- **THEN** the session is loaded and the step continues in it

#### Scenario: A resume with an agent that cannot

- **GIVEN** an agent that does not declare session loading
- **WHEN** the unit's step resumes
- **THEN** a new session starts and the log says the earlier session was not resumed
