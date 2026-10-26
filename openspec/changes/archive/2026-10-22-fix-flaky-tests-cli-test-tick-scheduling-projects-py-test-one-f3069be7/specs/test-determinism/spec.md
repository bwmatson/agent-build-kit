## ADDED Requirements

### Requirement: `tests/cli/test_tick_scheduling_projects.py::test_one_project_starts_its_next_unit_as_one_of_its_builds_ends_and_the_other_does_not` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time
