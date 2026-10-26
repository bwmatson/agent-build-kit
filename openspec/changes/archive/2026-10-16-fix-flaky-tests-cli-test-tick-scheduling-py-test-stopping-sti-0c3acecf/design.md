## Context

`tests/cli/test_tick_scheduling.py::test_stopping_still_awaits_the_builds_in_flight` passes alone and fails under load.

## Decisions

- Is the test racy, or is the code it exercises racy? Decide from the failure, then fix that one.
- The fix leaves nothing to wait on by the clock: an injected clock, an event waited on, or a step the test calls directly.
