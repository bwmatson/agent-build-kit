# Tasks

Acceptance: none — scheduling inside the pass; tier-1 tests over the round with a fake
planner, store, verifier and guard prove it.

## 1. [agent-build-kit] [tier1] One round, run by the tick and by every refresh

Done when the tick and each refresh of a running pass run the same round, so a new change,
a finished change, a killed run and a spent usage window are handled while builds run.

- [x] 1.1 Test: with one unit building and a free slot, a change added between refreshes
      is planned, written to the store and the page, and its ready unit starts in the same
      round.
- [x] 1.2 Test: a refresh with every change unchanged makes no planner call and changes no
      unit's state; a planner that raises is logged, the other steps still run, the pass
      continues, and the change is tried again at the next round.
- [x] 1.3 Test: a change whose units have all merged is verified and archived by a round
      while another unit builds; verification is skipped and logged when the live-stack lock
      is held, and done in a later round.
- [x] 1.4 Test: a unit marked running with no run and no thread is reclaimed by a round; one
      held by a live process, one in the pass's building set, and one just submitted whose
      worker has not taken its lock are not.
- [x] 1.5 Test: a round whose guard refuses records the pause once, starts nothing, and the
      builds in flight finish; the next round after the guard allows starts work again.
- [x] 1.6 Test: editing the tasks of a change whose unit is building re-plans it and leaves
      the running unit's state, branch and pull request, and the loop's started set,
      unchanged.
- [x] 1.7 Test: the tick and the loop call the same function, `--dry-run` and `--only`
      behave as before, and the readmission of a sent-back unit still happens in the round.
- [x] 1.8 Test: a unit whose thread an event resumed (marked running, no run, no process
      holds it) is started by the next round and is not counted against the cap while it waits;
      with the cap reached by real runs, a ready unit still waits; a unit in `building` counts.
- [x] 1.9 Extract the round, call it from the tick's start and from `_schedule`'s refresh,
      move the readmission and evaluation into it, gate verification on the live-stack
      lock, and pass the in-flight set to the reclaim.
- [x] 1.10 Update `docs/architecture.md` where the tick and the pass loop are described and
      add a changelog entry.
