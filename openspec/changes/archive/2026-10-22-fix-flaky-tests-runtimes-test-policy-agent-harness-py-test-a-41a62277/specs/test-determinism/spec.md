## ADDED Requirements

### Requirement: `tests/runtimes/test_policy_agent_harness.py::test_a_run_ended_once_the_agent_is_up_leaves_no_process_and_no_directory` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time
