## From `scratch-app-ignores-its-lock/1`

- test_scratch_app_unit_test.py: the new test copies the existing test's setup and command loop. Fold its two assertions into the existing test, or share one helper between them.
- Task 1.3 (run test_graph_acp_unit.py and test_acp_build_unit.py with an agent configured and report whether the rework step is reached) is a report, not code. Nothing in this diff shows it was done, so the PR reviewer should confirm that run took place.
- tests/integration/test_scratch_app_unit_test.py:44 — The new test repeats the existing test's setup and command loop line for line: build the app, add and commit test_marker.py, get the profile, build the lint and test commands, run each and assert exit 0. The only new part is the git-status assertion at the end.
