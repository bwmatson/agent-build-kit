## RENAMED Requirements

- FROM: `### Requirement: A test kind is one type with the values unit-test and e2e-test`
- TO: `### Requirement: A test kind is one type with the values unit-test, integration-test and e2e-test`

## MODIFIED Requirements

### Requirement: A test kind is one type with the values unit-test, integration-test and e2e-test

abk SHALL represent the kind of a test as one type whose values are `unit-test`, `integration-test` and `e2e-test`, and SHALL use that
type for the kind of a task group, a planned unit and a stored unit. A value that is not one of the three SHALL be refused as it is
today, naming the values that are accepted.

#### Scenario: The values

- **WHEN** the kind of a unit is read
- **THEN** it is `unit-test`, `integration-test` or `e2e-test`
- *Test level: unit.*

#### Scenario: An unknown kind

- **GIVEN** a heading tagged `[integration]`
- **WHEN** the change is read
- **THEN** it is refused, naming `unit-test`, `integration-test` and `e2e-test` as the tags accepted
- *Test level: unit.*
