## ADDED Requirements

### Requirement: A tier 2 test may start a real agent

The guards of the suite that refuse a real agent process, the runtime's spawn and a direct start of `claude`, SHALL NOT
apply to a test that carries the tier-2 marker, on the test, its class or its module, and SHALL apply to every other test
as they do now. The guards on refreshing the login, reading the usage window, running `gh` and reaching the code host SHALL
apply to every test, tier 2 included, and a tier 2 test that reaches one SHALL fail with that guard's message.

#### Scenario: A test without the marker is refused

- **GIVEN** a test that carries no tier marker and starts the runtime's real agent
- **WHEN** it runs
- **THEN** it fails with the message that names the injection it should use

#### Scenario: A tier 2 test is not refused

- **GIVEN** a test marked `local_stack` that starts a harmless program through the runtime's real spawn
- **WHEN** it runs
- **THEN** the program runs and no guard refuses it

#### Scenario: The marker on the module counts

- **GIVEN** a module whose tests are all marked `local_stack` through a module-level mark
- **WHEN** one of them starts the real spawn
- **THEN** it is not refused

#### Scenario: The direct start follows the same rule

- **GIVEN** a test marked `local_stack` and one without the marker, each starting a program whose name is `claude`
- **WHEN** they run
- **THEN** the first is not refused by the guard and the second is, with the guard's message

#### Scenario: The other guards hold for a tier 2 test

- **GIVEN** a test marked `local_stack` that refreshes the login, reads the usage window, runs `gh` or calls the code host
- **WHEN** it runs
- **THEN** it fails with that guard's message
