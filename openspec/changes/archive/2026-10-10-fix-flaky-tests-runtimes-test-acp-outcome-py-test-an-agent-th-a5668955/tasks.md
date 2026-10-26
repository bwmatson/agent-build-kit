# Tasks

Acceptance: none — a flaky test is made deterministic; nothing a consumer sees changes.

## 1. [agent-build-kit] [tier1] Make `tests/runtimes/test_acp_outcome.py::test_an_agent_that_ends_its_turn_but_leaves_stderr_held_has_that_holder_killed` deterministic

Priority: 2

Done when the test passes under load every time, and under the repeat check.

- [x] 1.1 Test: reproduce the race in `tests/runtimes/test_acp_outcome.py::test_an_agent_that_ends_its_turn_but_leaves_stderr_held_has_that_holder_killed` deterministically, without waiting on the clock, so it fails every time before the fix.
- [x] 1.2 Make the test pass: decide whether the test or the code it exercises is racy, fix that one, and run the test under the repeat check.
