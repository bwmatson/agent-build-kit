## From `fix-flaky-tests-cli-test-tick-scheduling-projects-py-test-one-f3069be7/1`

- test_a_pass_starts_four_units_of_each_project_with_four_workers still waits on the clock-bounded `WAIT`, the same weakness this unit fixed for the refill test. The follow-up the builder proposed is right: bound that wait with `HANG_GUARD`, remove `WAIT`, and in the same change remove or rewrite tests/cli/test_tick_scheduling_projects_starved.py. That file sets `WAIT` without raising=False, so it fails as soon as `WAIT` is removed.
