## From `a-failed-live-test-says-what-its-scratch-tick-did/1`

- tests/scratch_tick.py:147 — `_pause` writes its own copy of `_attempt`'s `<source> unavailable: <ErrorName>` message format, and its own `except Exception` with the same noqa.

## From `a-failed-live-test-says-what-its-scratch-tick-did/3`

- tests/test_scratch_dump.py:649 — The test is named `test_the_lock_of_a_running_e2e_test_is_shown_without_taking_it`, but it only checks that `(no e2e lock)` appears when the lock file is missing. That the holder is shown is checked in the every-source test, and that the lock is not taken is checked by the no-write test.
