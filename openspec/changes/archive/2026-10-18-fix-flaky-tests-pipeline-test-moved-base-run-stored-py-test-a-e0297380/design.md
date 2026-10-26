## Context

`tests/pipeline/test_moved_base_run_stored.py::test_a_running_pass_lets_a_handed_back_unit_in_and_still_refuses_the_causes_it_refused` passes alone and fails under load.

## Decisions

- Is the test racy, or is the code it exercises racy? Decide from the failure, then fix that one.
- The fix leaves nothing to wait on by the clock: an injected clock, an event waited on, or a step the test calls directly.
