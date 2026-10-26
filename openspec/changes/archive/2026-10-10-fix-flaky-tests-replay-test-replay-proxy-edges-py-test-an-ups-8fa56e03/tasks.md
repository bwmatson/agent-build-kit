# Tasks

Acceptance: none — a flaky test is made deterministic; nothing a consumer sees changes.

## 1. [agent-build-kit] [tier1] Make `tests/replay/test_replay_proxy_edges.py::test_an_upstream_that_cannot_be_reached_is_answered_502_and_nothing_is_recorded` deterministic

Priority: 2

Done when the test passes under load every time, and under the repeat check.

- [x] 1.1 Test: reproduce the race in `tests/replay/test_replay_proxy_edges.py::test_an_upstream_that_cannot_be_reached_is_answered_502_and_nothing_is_recorded` deterministically, without waiting on the clock, so it fails every time before the fix.
- [x] 1.2 Make the test pass: decide whether the test or the code it exercises is racy, fix that one, and run the test under the repeat check.
