## Context

`tests/cli/test_tick_committed_marker.py::test_a_tick_delivers_a_commit_made_and_not_delivered_once_and_removes_the_lease` passes alone and fails under load.

## Decisions

- Is the test racy, or is the code it exercises racy? Decide from the failure, then fix that one.
- The fix leaves nothing to wait on by the clock: an injected clock, an event waited on, or a step the test calls directly.
