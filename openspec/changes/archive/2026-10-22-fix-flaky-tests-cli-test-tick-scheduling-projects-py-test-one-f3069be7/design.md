## Context

`tests/cli/test_tick_scheduling_projects.py::test_one_project_starts_its_next_unit_as_one_of_its_builds_ends_and_the_other_does_not` passes alone and fails under load.

## Decisions

- Is the test racy, or is the code it exercises racy? Decide from the failure, then fix that one.
- The fix leaves nothing to wait on by the clock: an injected clock, an event waited on, or a step the test calls directly.
