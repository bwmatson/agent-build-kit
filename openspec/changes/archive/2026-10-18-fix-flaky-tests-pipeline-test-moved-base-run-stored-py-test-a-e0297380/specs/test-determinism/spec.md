## ADDED Requirements

### Requirement: `tests/pipeline/test_moved_base_run_stored.py::test_a_running_pass_lets_a_handed_back_unit_in_and_still_refuses_the_causes_it_refused` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time
