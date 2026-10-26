# Tasks

Acceptance: none — a flaky test is made deterministic; nothing a consumer sees changes.

## 1. [agent-build-kit] [unit-test] Make `tests/runtimes/test_policy_agent_harness.py::test_a_run_ended_once_the_agent_is_up_leaves_no_process_and_no_directory` deterministic

Priority: 1

Done when the test passes under load every time, and under the repeat check.

- [x] 1.1 Test: reproduce the race in `tests/runtimes/test_policy_agent_harness.py::test_a_run_ended_once_the_agent_is_up_leaves_no_process_and_no_directory` deterministically, without waiting on the clock, so it fails every time before the fix.
- [x] 1.2 Make the test pass: decide whether the test or the code it exercises is racy, fix that one, and run the test under the repeat check.
