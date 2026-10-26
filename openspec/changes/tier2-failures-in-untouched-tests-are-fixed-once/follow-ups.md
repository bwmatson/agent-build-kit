## From `tier2-failures-in-untouched-tests-are-fixed-once/1`

- `_judge` does not pass the session's timeout to the base rerun, and neither does the unit's own e2e-test command. If a base rerun hangs, it holds the stack lock as long as a hung unit run would. If e2e-test commands ever get a per-command timeout, give the base rerun the same one.

## From `tier2-failures-in-untouched-tests-are-fixed-once/2`

- docs/architecture.md:1039 — The new paragraph uses the present tense for two behaviours that only group 3 wires: that a pre-existing failure 'is appended' to the record when the base run names it, and that 'a unit waits on either kind until it merges'. In production nothing calls `preexisting_record().append` or `ensure_fix` yet.
- src/agent_build_kit/cli/pipeline.py:801 — The dry-run preview and its comment line sit inside the 'First, and silently… an idle tick should cost nothing' comment that explains the `has_work` early return. The preview therefore now separates that comment from the code it describes.
- tests/integration/test_untouched_failure_change_validates.py:41 — The successor case moves the first change into archive/ by renaming the directory. It does not merge the first change's ADDED requirement into specs/failing-tests/spec.md, as a real archive would. So it shows only that the MODIFIED delta validates, not that its requirement header matches the archived one.

## From `tier2-failures-in-untouched-tests-are-fixed-once/3`

- The saved e2e-test feedback still shows the snapshot's `**Failed:** N of M` count, which counts pre-existing tests, and the `**Full output:**` path, whose file holds their output. `abk status` reads that path back out of the feedback text. Moving the path into a stored field on the unit would let the agent-visible text leave it out. That is a separate change.
- tests/graph/test_e2e_feedback.py:150 — The new prompt test only checks prompts that contain OWN (`fixing = [p for p in prompts if OWN in p]`). A prompt sent in the next round that carries OLD_OUTPUT but not OWN would not be checked.
- tests/pipeline/test_e2e_resume.py:249 — The new moved-restack test checks `moved < unit-test < push` but not where e2e-test falls. It does not show that e2e-test runs again after the restack's unit-test.
