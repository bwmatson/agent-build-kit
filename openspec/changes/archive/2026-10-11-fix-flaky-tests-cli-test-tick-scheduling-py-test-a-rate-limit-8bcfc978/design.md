## Context

`tests/cli/test_tick_scheduling.py::test_a_rate_limit_pause_ends_at_its_deadline_within_the_pass` passes alone and fails under load.

## Decisions

- Is the test racy, or is the code it exercises racy? Decide from the failure, then fix that one.
- The fix leaves nothing to wait on by the clock: an injected clock, an event waited on, or a step the test calls directly.
