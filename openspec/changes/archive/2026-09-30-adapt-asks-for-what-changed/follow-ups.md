## From `adapt-asks-for-what-changed/1`

- `_adapt` in `src/agent_build_kit/pipeline/stack_runner.py` renders every decision the agent returned into the reviewer's note, including ones for names outside `required` (tests the unit never owned, or ones already counted as kept automatically, which then appear twice). Filtering `rendered` to names in `restacked.old_tests`, and dropping from it any name in `auto_kept`, would keep the note to this unit's own tests.
- `check_test_decisions` accepts an `adapt` with an empty reason for a test that is present and changed, although the prompt says "Say what changed". Requiring a non-empty reason there, as retirements already require one, would make the reviewer's note more useful.
