# Proposal

## Why

Where a unit's time goes can only be reconstructed by reading free-text log lines,
and the biggest parts are not logged at all: the time a ready unit waits for a slot,
the time it is paused for the usage window, and the time its pull request waits for
a person or for checks. A unit that took a day may have been building for twenty
minutes.

## What Changes

- **Each node's start and end are recorded** as a span in the same ledger the agent
  calls go to (`runs/usage-ledger.jsonl`), with UTC stamps, the unit, change, node,
  round and a wait bucket.
- **Waits are named.** Slot wait (ready to running), usage-pause wait (the gate's
  interrupt to its resume), and review wait (an `in_review` interval from the unit's
  history, which can be split into checks and people by the pull request's check
  results).
- **Checks are timed** per tier 1 command, from the existing `passed, Ns` timing,
  into the same record.
- **UTC throughout.** Run log lines keep their local stamps; the ledger does not use
  them.
- **Recording never affects a run**, as for agent calls.
