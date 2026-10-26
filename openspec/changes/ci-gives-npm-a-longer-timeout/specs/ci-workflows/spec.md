## ADDED Requirements

### Requirement: The OpenSpec fetch allows a slow registry

The step that fetches the pinned OpenSpec CLI SHALL give each of its three attempts a limit read from `OPENSPEC_ATTEMPT_TIMEOUT` seconds, 300 when the
variable is unset, and SHALL set `timeout-minutes` to at least the three attempts at that default plus the delays between them, with margin (20). The number
of attempts, the removal of the npx cache between attempts and the final message SHALL be as before.

#### Scenario: The default limit

- **GIVEN** `OPENSPEC_ATTEMPT_TIMEOUT` is unset
- **WHEN** the script makes an attempt
- **THEN** `timeout` is called with 300 as its limit

#### Scenario: A limit from the environment

- **GIVEN** `OPENSPEC_ATTEMPT_TIMEOUT=7`
- **WHEN** the script makes an attempt
- **THEN** `timeout` is called with 7

#### Scenario: The step limit fits the attempts

- **WHEN** the guard test reads the `integration` job's fetch step
- **THEN** its `timeout-minutes` is at least 16 and the script's default attempt limit is 300
