# Design

## Method

Each group is a refactor of tests with no change in what they assert. For a test that sleeps to order two actors, the
actors signal; for a test that polls, it waits through `tests/waiting.wait_for`, the one shared way to wait for a
condition, or on an event; for a fixed delay that stands in for "several refreshes", it waits until a counter says the
refreshes happened. A group ends by removing its files from the allowlist in `tests/timing_hazards.py`, so the guard fails
if one of the uses comes back. The guard's own check that an allowlisted file still holds a hazard, added by
`flaky-tests`, is what keeps the list from going stale: a group that fixes a file and leaves its entry fails the guard
test, and the group that removes the entry is the group that fixed it.

Each rewritten test must pass the pipeline's repeat check, which runs added and changed tests `limits.tier1_repeat_runs`
times (three by default) under load; the group states in its pull request that it did. A figure larger than the
pipeline's is not asked of a group.

## What the code holds today

The guard reports sleeps, threads that nothing joins or signals, and literal non-zero ports. It does not report clock
reads. The hazards, by file:

- `pipeline/test_tier2.py`: two sleeps in the lock test, which decide the order of two holders.
- `graph/test_thread_resume.py`: a 0.05-second sleep in a loop that waits for a marker file written by a child process.
- `cli/test_round.py`: the local `eventually`, and a thread joined with `join(WAIT)`; the guard accepts a join only with a
  literal or a `timeout=` keyword, so the constant argument is why it still reports it.
- `cli/test_tick_scheduling.py`: its own `eventually`, imported by the host-outage test, and one fixed 0.4-second sleep.
- `cli/test_tick_host_outage_backoff.py`: the same fixed sleep.
- `pipeline/test_scratch_folder.py`: a local `wait_until` with a sleep.
- `serve/test_chat_guards.py`: a 0.6-second sleep before an assertion on the lock holder.
- `serve/test_serve_metrics.py` and `test_telemetry.py`: `serve_forever` threads started and never joined.
- `integration/test_telemetry_stack.py`: a three-second sleep in a poll against a real stack, run only locally.
- `serve/test_serve_binding.py`: a UDP `connect` to a documentation address to learn the local address. No server is
  started; the guard reads the call as a fixed port.

## The groups

1. The lock ordering test, whose result depended on one sleep being shorter than another. The first holder sets an event
   once inside the lock; the second runs the lock with `on_wait`, which `stack_lock` already calls when it has to wait,
   and that callback releases the first. No sleep remains, and the second holder having blocked is shown, not assumed.
2. The subprocess tests and helpers: `tests/graph/test_thread_resume.py` waits for the child's marker through
   `wait_for`, and `tests/chat_serving.py::until` becomes a call to `wait_for` or goes, with its callers using it. No
   test polls a process listing today; the one place that reads `/proc` is the serve tests' fixture that kills agents a
   test leaves running, and replacing it with the helpers registering their pids is optional and not tied to the
   allowlist.
3. The round and tick tests, together with the scratch-folder test: the copies of `eventually` and `wait_until` are
   replaced by `wait_for` and deleted; the two 0.4-second sleeps wait for a counted number of refreshes (a counter on the
   tick driver in `tests/tick_driver.py`, which wraps `poll_all` already, shared by both tests); the round test's thread
   is joined with `timeout=`.
4. The web and telemetry tests: the chat-guards sleep waits on the lock holder reaching its expected value; the metrics and
   telemetry fake servers are shut down and joined in the same function that starts them; the Azure fake host's delay is
   released by a gate instead of slept. Optional in this group, each only if cheap: the telemetry-stack poll, which runs
   only against a real stack and has never been seen to flake, and the route probe in `serve/test_serve_binding.py`, which
   can either be written so that the guard does not read it as a port or stay on the allowlist with the reason written
   beside the entry.

Groups 1 and 2 are small and the planner may carry them in one unit; group 3 is the largest; the change as a whole is in the
order of three to four hundred lines.

## Order and conflicts

This change does not wait for `dry-cleanup`. That change is four planned units of some two thousand lines behind a failed
unit, and holding this one idle behind it buys little: the overlap is the duplicated `eventually` helpers, and this
change deletes those copies itself by using `wait_for`. If `dry-cleanup`'s move of test helpers lands later, it may need a
trivial rebase over those deletions.

`tests/cli/test_tick_scheduling.py` is the hot spot: it has had many commits in the days before this was written, and the
running `an-internet-outage-is-not-a-failure` change edits the tick tests. Re-read that file, `tests/tick_driver.py` and
the host-outage test just before group 3 starts, and start it from the current trunk.
