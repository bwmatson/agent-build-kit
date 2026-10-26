## ADDED Requirements

### Requirement: `tests/cli/test_tick_committed_marker.py::test_a_tick_delivers_a_commit_made_and_not_delivered_once_and_removes_the_lease` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time
