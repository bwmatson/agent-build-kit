# Tasks

Acceptance: none — the count and the choice are pure over a unit graph; tier-1 tests prove each case.

Priority: 2

## 1. [agent-build-kit] [tier1] A blocked unit gives its place to the unit blocking it

Needs: start-order-by-stack-age group 1 merged — this change reorders the same choice and builds on its effective age
Needs: unit-priority group 1 merged — the handoff is ordered by effective priority and reuses its waiting-set helper

Done when a blocked planned unit is not counted, its prerequisite starts into its place within the limit, and an unblocked unit waits
for room.

- [x] 1.1 Test: a planned unit with work that waits on a prerequisite, a predecessor reworking, failed or held, or the cause `gated`
      or `upstream_went_back` is blocked and not counted; running, in review and failed units are counted and a held unit is not; a
      backoff, a lease, a unit left out of a limited tick and a usage pause do not make a unit blocked.
- [x] 1.2 Test: at the limit a ready prerequisite of a blocked unit that had work starts into its place ahead of every other unit and the
      count stays within the limit; a prerequisite of a unit that never started gets no handoff; two blocked units on one
      prerequisite give it one place and the other goes to the next unit by the usual order; several prerequisites are ordered by
      effective priority, then effective age; the cap on units running at once, a limited tick, a lease and a backoff are respected.
- [x] 1.3 Test: a planned unit that is no longer blocked stays planned while the number of other units in progress is at the limit and
      starts when one finishes; a planned unit paused by a usage pause resumes at the limit; a rework, a restack, a review round, a push
      and opening a pull request proceed at the limit.
- [x] 1.4 Test: the queue line and the status give the number of blocked units not counted and what each waits on, and the graph
      labels a blocked unit as blocked.
- [x] 1.5 Add a blocked predicate beside `waiting_on`, change `in_progress` and the count of free places, choose the handoff units
      before the classes in `ready_units`, require room for an unblocked planned unit, and report the blocked units in the
      evaluation, the queue line, the reason nothing started and the status.
- [x] 1.6 Update `docs/architecture.md` (the paragraphs on units in progress and on free places), `docs/unit-graph.md` and the pipeline
      skill, and add a changelog entry.
