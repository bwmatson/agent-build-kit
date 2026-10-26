## ADDED Requirements

### Requirement: `tests/runtimes/test_policy_agent_harness.py::test_an_agent_that_never_answers_ends_at_the_deadline_with_nothing_left` is deterministic

The test SHALL give the same result however loaded the machine running it is.

#### Scenario: Run repeatedly under load

- **WHEN** the test is run repeatedly under parallel load
- **THEN** it passes every time
