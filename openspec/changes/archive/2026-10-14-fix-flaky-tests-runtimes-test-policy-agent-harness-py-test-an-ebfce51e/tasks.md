# Tasks

Acceptance: none — a flaky test is made deterministic; nothing a consumer sees changes.

## 1. [agent-build-kit] [tier1] Make `tests/runtimes/test_policy_agent_harness.py::test_an_agent_that_never_answers_ends_at_the_deadline_with_nothing_left` deterministic

Priority: 1

Done when the test passes under load every time, and under the repeat check.

- [x] 1.1 Test: reproduce the race in `tests/runtimes/test_policy_agent_harness.py::test_an_agent_that_never_answers_ends_at_the_deadline_with_nothing_left` deterministically, without waiting on the clock, so it fails every time before the fix.
- [x] 1.2 Make the test pass: decide whether the test or the code it exercises is racy, fix that one, and run the test under the repeat check.
