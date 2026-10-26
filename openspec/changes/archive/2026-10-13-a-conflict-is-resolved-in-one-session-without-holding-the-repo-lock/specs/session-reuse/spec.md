## MODIFIED Requirements

### Requirement: Every agent node records its session under a role

When an agent node completes, the pipeline SHALL record the session it ran in, with the
runtime that owns the id, the model the session started with, the round and the branch head,
under the node's role in the unit's state. The roles SHALL be `build`, for `tests`,
`implement`, `fix_checks`, `rework`, `adapt` and `restack`, and `review`, for `review`. A role's record
SHALL NOT be overwritten by a node of another role, and SHALL be kept after the node
completes. A unit's state saved before this requirement SHALL load with no recorded sessions.

#### Scenario: Two roles in one unit

- **GIVEN** a unit whose `implement` ran in one session and whose `review` ran in another
- **WHEN** both nodes have completed
- **THEN** the state holds both sessions, each under its own role

#### Scenario: A later node of the same role

- **GIVEN** a recorded `build` session from `implement`
- **WHEN** `fix_checks` completes
- **THEN** the `build` record names `fix_checks` as the last node to speak in it

#### Scenario: A unit saved before this change

- **GIVEN** a unit state with no recorded sessions
- **WHEN** it is loaded and a node runs
- **THEN** the node starts a new session and records it

#### Scenario: A conflict resolved in the build session

- **GIVEN** a unit with a recorded `build` session and reuse on
- **WHEN** a restack conflict is resolved by the restack step
- **THEN** the step continues that session, and the `build` record names `restack` as the last node to speak in it

#### Scenario: A unit whose first agent call is the restack

- **GIVEN** a unit resumed with no recorded `build` session
- **WHEN** a restack conflict is resolved by the restack step
- **THEN** the step starts the build session on the rework model, and the next build node continues it
