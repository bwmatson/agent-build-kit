# Tasks

Acceptance: none — the change is in the pipeline's own scheduling, with no
surface a consumer drives; what proves it is a tier-1 test whose builder
completes in a controlled order, which fails against the fixed-batch behaviour
it replaces.

## 1. [agent-build-kit] [tier1] Keep the slots full while a pass runs

Done when a unit finishing mid-pass causes whatever it unblocked to start in
that same pass, the caps and dependency rules still hold on every evaluation,
and a pass that must stop stops.

- [x] 1.1 Test: with a fake builder whose completions are controlled, a parent
      finishing mid-pass starts its child in the same pass, and a unit set back
      to planned during the pass is started by it — both fail against a pass
      that fixes its batch at the start.
- [x] 1.2 Test: a long-running unit does not keep the other slots idle; no more
      than the concurrency cap build at once across repeated evaluations; a
      chain already past the depth cap is still held back; and no unit is ever
      started twice in one pass.
- [x] 1.3 Test: when a build reports the pass should stop, nothing further is
      started and the in-flight builds are still awaited; and a pass narrowed to
      one unit starts nothing else even after that unit unblocks another.
- [x] 1.4 Test: each evaluation refreshes from the code host before deciding, a
      dependency that merges mid-pass releases its dependent, a failing refresh
      is logged and the pass continues, and planning happens once per pass.
- [x] 1.5 Replace the fixed batch with a scheduling loop: a pool sized to the
      concurrency cap, completions awaited one at a time, and each completion
      followed by a refresh and a fresh readiness evaluation against the store,
      tracking what this pass has already started.
- [x] 1.6 Act on the builder's report that the pass should stop, which the
      concurrent path currently discards, and apply the narrowing to every
      evaluation.
- [x] 1.7 Say in `docs/architecture.md` — and in the `abk-pipeline` skill, where
      a pass is described — that a pass keeps scheduling until it runs out of
      ready work, so a pass is what to watch rather than a unit.
