## Context

`tests/runtimes/test_acp_outcome.py::test_an_agent_that_ends_its_turn_but_leaves_stderr_held_has_that_holder_killed` passes alone and fails under load.

## Decisions

- Is the test racy, or is the code it exercises racy? Decide from the failure, then fix that one.
- The fix leaves nothing to wait on by the clock: an injected clock, an event waited on, or a step the test calls directly.
