# Tasks

Acceptance: none — test refactors; each group's rewritten tests pass the pipeline's repeat check and the guard enforces the gain.

Priority: 3

## 1. [agent-build-kit] [tier1] Ordering by signal in the lock test

Done when the lock test orders its two holders by signal and its file is off the allowlist.

- [x] 1.1 Test: `tests/pipeline/test_tier2.py::test_a_second_run_waits_for_the_first` still asserts the order of the two
      holders and passes the unit's repeat check, and the guard test fails while `pipeline/test_tier2.py` stays on the allowlist
      once its two sleeps (near lines 38 and 42) are gone.
- [x] 1.2 Rewrite it: the first holder sets an event once it holds the lock; the second takes the lock with `stack_lock`'s
      `on_wait` callback, which releases the first, so the test shows that the second blocked. Remove the file from the allowlist.
- [x] 1.3 Add a changelog entry.

## 2. [agent-build-kit] [tier1] The subprocess tests and helpers wait on events

Done when `tests/graph/test_thread_resume.py` and `tests/chat_serving.py` no longer poll with a sleep and the first file is
off the allowlist.

- [x] 2.1 Test: the rewritten `tests/graph/test_thread_resume.py` test covers what it did (a process killed while a node
      runs leaves the thread resumable at that node) and passes the unit's repeat check; the guard test fails while the file stays
      on the allowlist; the serve tests that use `until` still pass.
- [x] 2.2 In `tests/graph/test_thread_resume.py`, wait for the child's `running` marker with `tests.waiting.wait_for`
      (still failing at once if the child exits first) instead of the sleep in the loop (near line 109), and remove the file
      from the allowlist. In `tests/chat_serving.py`, make `until` (near line 220) a call to `wait_for`, or delete it and
      have its callers use `wait_for`.
- [x] 2.3 Optional, only if it stays small: replace the autouse fixture in `tests/serve/conftest.py` that scans
      `/proc/*/cmdline` and kills a test's leftover fake agents with the helpers that start them registering their pids
      and ending them in teardown. It is not a guard hazard and no allowlist entry depends on it.
- [x] 2.4 Add a changelog entry.

## 3. [agent-build-kit] [tier1] The round and tick tests wait on events

Done when the round, tick and scratch-folder tests wait through `wait_for` or a counter and their four files are off the
allowlist. Re-read `tests/cli/test_tick_scheduling.py` and `tests/cli/test_tick_host_outage_backoff.py` before starting:
other changes edit them.

- [x] 3.1 Test: the rewritten tests in `tests/cli/test_round.py`, `tests/cli/test_tick_scheduling.py`,
      `tests/cli/test_tick_host_outage_backoff.py` and `tests/pipeline/test_scratch_folder.py` cover what the originals did and pass the unit's
      repeat check; a test of the counter shows it reaches N after N refreshes; the guard test fails while any of the four files stays on
      the allowlist.
- [x] 3.2 Add to `tests/tick_driver.py` a count of the refreshes (`poll_all` runs) that a test can wait on with
      `wait_for`. Replace the fixed 0.4-second sleeps in `tests/cli/test_tick_scheduling.py` (near line 1346) and
      `tests/cli/test_tick_host_outage_backoff.py` (near line 114) with waiting for a number of refreshes through it, then
      asserting no readmission.
- [x] 3.3 Delete the local `eventually` copies in `tests/cli/test_round.py` (near line 55) and
      `tests/cli/test_tick_scheduling.py` (near line 66; the host-outage test imports this one) and the `wait_until` in
      `tests/pipeline/test_scratch_folder.py` (near line 263), and use `wait_for` instead. Join the thread in `tests/cli/test_round.py`
      (near line 305) with `timeout=`, which the guard accepts. Remove the four files from the allowlist.
- [x] 3.4 Add a changelog entry.

## 4. [agent-build-kit] [tier1] The web and telemetry tests leave no sleep or thread behind

Done when the chat-guards sleep, the unjoined server threads and the Azure fake host's sleeping delay are gone and their files
are off the allowlist or, for the two optional entries, kept with a stated reason.

- [x] 4.1 Test: the rewritten tests in `tests/serve/test_chat_guards.py`, `tests/serve/test_serve_metrics.py` and
      `tests/test_telemetry.py` cover what the originals did, and the tests that use the Azure fake host's delay still pass,
      all passing the unit's repeat check; the guard test fails while any of the three files stays on the allowlist.
- [x] 4.2 In `tests/serve/test_chat_guards.py` replace the 0.6-second sleep (near line 86) with `wait_for` on the lock holder
      reaching the value the test asserts. In `tests/serve/test_serve_metrics.py` (near lines 81, 124 and 373) and
      `tests/test_telemetry.py` (near line 110) shut the server down and join its thread in the function that starts it. Remove the three files
      from the allowlist.
- [x] 4.3 In `tests/forges/azure_rest_host.py` make the `delay` (near line 159) a gate that a test releases, instead of a sleep.
- [x] 4.4 Optional: remove the three-second sleep in the poll at `tests/integration/test_telemetry_stack.py` (near line
      190), which only runs against a real stack, and teach the guard (or write `tests/serve/test_serve_binding.py`'s UDP route probe to
      `192.0.2.1`) so it is not read as a fixed port. Any file left on the allowlist keeps a reason written beside its entry in `tests/timing_hazards.py`.
- [x] 4.5 Add a changelog entry.
