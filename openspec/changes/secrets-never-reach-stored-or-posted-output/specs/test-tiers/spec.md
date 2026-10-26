## ADDED Requirements

### Requirement: Test-support objects do not show their environment in a failure message

An object that a test fixture or helper hands to tests and that carries an environment dictionary SHALL leave that field out of its repr, so that a failed assertion which prints the
object does not print the environment. The framework's acceptance tests' `Scratch` objects SHALL do so. A tier-1 test SHALL fail for any such object under the tests whose repr holds
a value of its environment.

#### Scenario: The scratch object

- **GIVEN** a `Scratch` built with an environment holding a sample secret value
- **WHEN** its repr is taken
- **THEN** the value does not appear, and its other fields do

#### Scenario: A new support object that forgets the rule

- **GIVEN** a test-support model with an `env` field that is part of its repr
- **WHEN** the tier-1 test runs
- **THEN** it fails naming the model

#### Scenario: An assertion that prints the object

- **WHEN** an acceptance test fails on an assertion whose message includes the `Scratch` object
- **THEN** the failure text holds no environment value
