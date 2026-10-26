## Context

`tests/runtimes/test_policy_agent_harness.py::test_a_command_refused_without_a_terminal_request_is_refused_and_one_run_is_reached` passes alone and fails under load.

## Decisions

- Is the test racy, or is the code it exercises racy? Decide from the failure, then fix that one.
- The fix leaves nothing to wait on by the clock: an injected clock, an event waited on, or a step the test calls directly.
