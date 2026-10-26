# Tasks

Acceptance: none — a flaky test is made deterministic; nothing a consumer sees changes.

## 1. [agent-build-kit] [tier1] Make `tests/cli/test_tick_committed_marker.py::test_a_tick_delivers_a_commit_made_and_not_delivered_once_and_removes_the_lease` deterministic

Priority: 2

Done when the test passes under load every time, and under the repeat check.

- [x] 1.1 Test: reproduce the race in `tests/cli/test_tick_committed_marker.py::test_a_tick_delivers_a_commit_made_and_not_delivered_once_and_removes_the_lease` deterministically, without waiting on the clock, so it fails every time before the fix.
- [x] 1.2 Make the test pass: decide whether the test or the code it exercises is racy, fix that one, and run the test under the repeat check.
