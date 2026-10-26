## ADDED Requirements

### Requirement: `tests/runtimes/test_policy_agent_harness.py::test_a_command_refused_without_a_terminal_request_is_refused_and_one_run_is_reached` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time
