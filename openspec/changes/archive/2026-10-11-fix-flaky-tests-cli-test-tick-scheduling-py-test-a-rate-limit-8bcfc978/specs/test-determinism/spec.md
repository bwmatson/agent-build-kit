## ADDED Requirements

### Requirement: `tests/cli/test_tick_scheduling.py::test_a_rate_limit_pause_ends_at_its_deadline_within_the_pass` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time
