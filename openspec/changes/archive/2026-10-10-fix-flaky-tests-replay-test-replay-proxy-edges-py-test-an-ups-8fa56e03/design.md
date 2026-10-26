## Context

`tests/replay/test_replay_proxy_edges.py::test_an_upstream_that_cannot_be_reached_is_answered_502_and_nothing_is_recorded` passes alone and fails under load.

## Decisions

- Is the test racy, or is the code it exercises racy? Decide from the failure, then fix that one.
- The fix leaves nothing to wait on by the clock: an injected clock, an event waited on, or a step the test calls directly.
