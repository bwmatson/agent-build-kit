## ADDED Requirements

### Requirement: `tests/cli/test_tick_scheduling.py::test_stopping_still_awaits_the_builds_in_flight` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time
