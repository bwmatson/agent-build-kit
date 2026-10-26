# Proposal

## Why

`flaky-tests` stops new timing hazards and lists today's as a baseline that may only shrink. Eleven test files are
still on that allowlist: `cli/test_round.py`, `cli/test_tick_host_outage_backoff.py`, `cli/test_tick_scheduling.py`,
`graph/test_thread_resume.py`, `integration/test_telemetry_stack.py`, `pipeline/test_scratch_folder.py`,
`pipeline/test_tier2.py`, `serve/test_chat_guards.py`, `serve/test_serve_binding.py`, `serve/test_serve_metrics.py` and
`test_telemetry.py`. Their hazards are bare sleeps, polling loops written with a sleep, and server threads nothing joins.
The worst is a test whose outcome depends on which of two sleeps wakes first.

This change is prevention, not a cure. The flake record holds five entries, and the merged `fix-flaky-tests` changes fixed
all five. None of the eleven files still on the allowlist has flaked. What the change buys is that a busy machine, or a
change that makes one of these tests slower, cannot start the first flake there, and that the allowlist, which may only
shrink, shrinks to what is left for a stated reason.

## What Changes

- **Order that depended on sleeps depends on events:** a test of two concurrent holders of a lock waits on a signal that
  the first holds it, and on the lock's own wait notice to show that the second blocked, instead of sleeping for longer
  than the second.
- **Subprocess tests and helpers wait on events:** the one subprocess test that polls a marker file with a sleep, and the
  chat-serving helper's polling `until`, wait through the shared `wait_for`. Optionally the serve tests' scan of the
  process table is replaced by the helpers registering what they start.
- **The round and tick tests wait through the shared `wait_for`:** the three copies of `eventually` and the scratch-folder
  test's own poll go, the two fixed 0.4-second sleeps that stand in for "several refreshes" wait for a counted number of
  refreshes instead, and the round test's thread is joined in a form the guard accepts.
- **The web and telemetry tests stop leaving threads and sleeps behind:** the chat-guards sleep waits on the server
  noticing, the fake servers' `serve_forever` threads are shut down and joined, and the Azure fake host's delay is released
  by a gate.
- **Each group removes its files from the guard's allowlist,** and the guard's existing check that an allowlisted file
  still has a hazard keeps the list honest.

Left alone: the fixed-port goal (every fake server here already binds port 0; the one fixed-looking address the guard
reports is a route probe, not a server) and the wall-clock goal (the guard does not detect clock reads, so there is
nothing to enforce or measure).

## Impact

- agent-build-kit: tests and test helpers only, plus any production code that needs a step to be testable. No behaviour
  change.
