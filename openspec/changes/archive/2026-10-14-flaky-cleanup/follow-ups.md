## From `flaky-cleanup/1`

- Task 2.3 (optional): replace the /proc-scanning autouse fixture in tests/serve/conftest.py with the fake-agent helpers registering and ending their own pids. It is ticked [x] in tasks.md, but this branch does not change tests/serve/conftest.py. Either untick it or record that it was skipped as not small.
- tests/test_timing_guard.py:256 — ALLOWLIST_CEILING still lists graph/test_thread_resume.py and pipeline/test_tier2.py after both left ALLOWLIST in tests/timing_hazards.py.
- tests/pipeline/test_tier2.py:45 — The on_wait callback's parameter is named `_who`, but stack_lock passes it the waiting message from _waiting_message (who holds the lock and for how long), not a holder name.

## From `flaky-cleanup/2`

- Move the hand-rolled HTTP servers in tests/otlp.py, tests/fake_gateway.py and tests/cli/test_telemetry_push_dashboard.py onto tests.http_thread.serving. This is the earlier optional point 1.5, which the builder left for a later unit; record it as a follow-up in the planning repo.
