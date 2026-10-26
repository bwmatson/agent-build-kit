# Tasks

Acceptance: none — durations recorded from the graph and the tick; tier-1 tests with
a fake clock prove it. `usage-report` carries the end-to-end acceptance.

## 1. [agent-build-kit] [tier1] Durations by node and wait

Done when a unit's nodes, slot waits, usage-pause waits and tier 1 commands leave span
records with UTC stamps and a wait bucket, and recording cannot affect a run.

- [x] 1.1 Test: with a fake clock, a node that runs for a known time writes one span
      with the unit, change, node, round, start, end and duration; a node that raises
      writes one with the failure outcome.
- [x] 1.2 Test: a unit submitted to the pool while all slots are busy records the
      wait from submit to lock acquisition with bucket `slot`.
- [x] 1.3 Test: a gate interrupt followed by a resume records the pause with bucket
      `usage_pause`.
- [x] 1.4 Test: each tier 1 command's duration is recorded under its command.
- [x] 1.5 Test: an unwritable ledger changes nothing about the run.
- [x] 1.6 Record spans in the node wrapper and the gate, the queue time in the tick's
      submit and worker, and the command durations in `build_tier1`.
- [x] 1.7 Describe the spans and buckets in `docs/architecture.md` and
      `docs/unit-graph.md`, and add a changelog entry.
