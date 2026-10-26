# Design

## Measured

All run in a throwaway worktree of `origin/main` (7e04c86), with the marker deselect overridden so the
serial modules ran in the parallel pass.

- VERIFIED: each of the ten modules, alone under `-n 8`, 5 times each (50 runs): 50 passed, 0 failures.
  Counts are 8, 8, 9, 16, 1, 16, 6, 13, 17 and 4 tests; each run takes 4 to 12 seconds, mostly worker
  start.
- VERIFIED: the whole `tests/serve` directory (279 tests) under `-n auto --maxprocesses=8`, 3 times:
  3 of 3 passed, in 20 to 22 seconds.
- VERIFIED: no collision showed up as a failure, so nothing about ports, working directories, the
  agent's home directory or the environment was seen to collide. UNVERIFIED: that those are not shared;
  only the process scan is known to be a mechanism, from the code.
- VERIFIED by search: constant session ids repeated across modules. `0b7e1d52-9c3a-4f8e-b1d6-2a5c7e9f0d41`
  is defined in `test_chat_editing.py`, `test_chat_commit.py`, `tests/cli/test_tick_committed_marker.py`
  and `tests/cli/test_attach_release_adopted.py`. `6d2a8f14-3e5b-4c7a-9f0e-1b8d3c6a2e71` is
  the free session in both `test_chat_planning_commit.py` and `test_chat_free_session_edits.py`, and `7e1c5a30-2b4d-4f86-a3c9-d0e8b6f21a47` is
  in `tests/pipeline/test_call_record.py` and `tests/graph/cost_fakes.py`, and
  `3f1c2a9e-5b7d-4e2f-9a61-0c8d7e4b2a15` in `tests/pipeline/test_transcript.py` and
  `tests/runtimes/claude_cli.py`. Ids that differ only in a digit are distinct strings and do not collide.
  The `tests/cli/` and `tests/pipeline/` ones are not serial, so they already run in parallel with
  the chat modules; whether they start processes with the id is UNVERIFIED.
- VERIFIED: timing, once each: the serial pass (98 tests) 64 s; the parallel pass of the rest
  153 to 176 s over two runs. Removing the serial pass saves about a minute of roughly four.
- VERIFIED, unrelated: in the parallel pass of the rest, 3 tests in `tests/hooks/test_policy.py` failed
  in both runs in the throwaway worktree. They are not part of this change; UNVERIFIED whether they
  fail in the main checkout.
- UNVERIFIED: how many of the chat tests need a real process list at all, and which; the sessions module
  already uses a random id per process.

## Why unique ids, not a lock

A serial pass fixes the collision by never running two tests at once. Unique ids remove it, which keeps
the tests safe in any worker count and for any later module, and lets the guard test state the rule.
The id is made in a fixture so a test cannot forget; a module constant is the thing the guard refuses.

## The seam

The lookup of who holds a session already takes the process-table location as a parameter, and the
guard that only trusts the real table already refuses a fake one for the destructive steps. The chat
object's two lookups do not pass it. They accept an optional location and pass it down, default
unchanged, so a test can point it at a tree it built in a temporary directory. Tests that only need an
answer to "who holds this" use that; one test per lookup keeps the real scan with a real detached
process and a fixture-made id, so the scan itself stays covered.

## Order and the marker

Modules lose the marker one at a time, each after 10 repeats under `-n auto`. A module that fails there
keeps the marker with a comment line saying what it cannot share. The serial pass and its
"collected nothing" exemption in the whole-suite command stay only while a marker remains; with none,
the marker definition and the second pass go, and the stale comment with them.

## Size

One group: ten mechanical module edits, a fixture, a signature, a guard and the config; well under the
750-line planner ceiling. UNVERIFIED until the diff exists; split by module if it runs over.
