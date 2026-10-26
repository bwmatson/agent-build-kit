## ADDED Requirements

### Requirement: A caller can choose the environment of the agents the web UI's server starts

The web UI's server SHALL accept, when it is started from code, a complete environment for the agent processes it starts
or asks. Every agent the server starts for a chat turn, a new session, a continued or forked session, and the check
whether a session would be resumed SHALL run in exactly that environment, with only the per-call variables of the request
added on top, and SHALL NOT see a variable that only the starting process has. When none is given, the agent SHALL run in
the starting process's environment as it does without this requirement, and `abk serve` SHALL give none. Every runtime that
starts an agent process SHALL honour the environment of its request the same way. A resume check answered in one
environment SHALL NOT be reused for another.

#### Scenario: The default is the process environment

- **GIVEN** a server started with no environment
- **WHEN** a chat turn starts an agent
- **THEN** the agent's environment is the starting process's, as before

#### Scenario: A given environment reaches the agent of a chat turn

- **GIVEN** a server started with an environment holding a variable the starting process does not have, and the starting
  process holding another variable the given environment lacks
- **WHEN** a chat turn runs on a build session
- **THEN** the agent sees the first variable and does not see the second

#### Scenario: A new and a continued session

- **GIVEN** a server started with an environment
- **WHEN** a new session and a continued session are started on each runtime
- **THEN** every agent process sees the given environment and no other

#### Scenario: The resume check asks in the same environment

- **GIVEN** an agent that lists a session only when a variable of the given environment is set
- **WHEN** the server checks whether the session would be resumed
- **THEN** the answer is yes, and a check made without the environment on the same session is answered separately

#### Scenario: Per-call variables are still added

- **GIVEN** a request with an environment and a gateway key in its added variables
- **WHEN** the agent starts
- **THEN** it sees the key as well as the environment

#### Scenario: A person's server is unchanged

- **WHEN** `abk serve` starts the server
- **THEN** it passes no environment and its agents run as before
