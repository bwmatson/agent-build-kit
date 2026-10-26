# Tasks

Acceptance: none — scheduling and bookkeeping inside the pipeline; tier-1 tests over
every hold path, the readmission rule and the events prove it.

## 1. [agent-build-kit] [tier1] A cause on every state change, and readmission by it

Done when a unit sent back for a moved base or a rework is let back into the running
pass whatever wording its note has, every other hold is skipped with a logged reason,
and no code reads a note to decide.

- [x] 1.1 Test: table-driven over every hold path of the graph's rebase and boundary
      nodes and the poller's rework handler: each records the expected cause, and
      `_sent_back` counts exactly the rework and base-changed ones.
- [x] 1.2 Test: a unit whose note is `base moved before its push: …` is readmitted; one
      held for toolchain, depth, review escalation or an upstream that went back is not,
      and the skip is logged with its cause.
- [x] 1.3 Test: rewording a note changes no decision; the diagram's reworking, paused
      and blocked labels follow the cause.
- [x] 1.4 Test: a store with old entries (the old `held before` and `rework requested`
      notes, the reviewer-hold note, a depth hold) loads with `cause=None`, `held_by`
      and `held_base` absent; the pass does not readmit them and no scheduling or
      diagram decision changes with their notes; a test fails if any module still
      imports the deleted matchers.
- [x] 1.5 Add `Cause`, the `cause` argument on `set_state` and the history entry, pass
      it from every writer, make `base_moved` and `upstream_incomplete` return a cause,
      rewrite `_sent_back` and `effective_state`, store the depth hold's base as a
      field, and delete `held_for_base`, the `held before` prefix checks, the reviewer-hold
      note comparison and the depth-hold regex.
- [x] 1.6 Add `abk status` output (or a documented command) listing every unit that is
      `planned` or `held` with no cause, so the ones in flight at cutover can be requeued
      or re-held once by hand.
- [x] 1.7 Update `docs/architecture.md` and the `abk-pipeline` skill where they
      describe how a pass readmits units and how to deal with a unit that has no cause,
      and add a changelog entry.

## 2. [agent-build-kit] [tier1] Events and feedback carry kinds

Done when requeue reasons, rework kinds and feedback sources are fields and no handler
parses their text.

- [x] 2.1 Test: each requeue mode (restart, released, resume, from failure, parent
      merged) takes its handling from `RequeueReason`; changing the reason text changes
      nothing.
- [x] 2.2 Test: each poller event (failing checks, conflict, label, changes requested,
      comment) reaches the rework with its `ReworkKind` and gets the feedback that kind
      calls for.
- [x] 2.3 Test: feedback from a person that begins with a check-failure phrase is
      treated as review feedback; feedback from tier 1 or tier 2 selects the fix-the-
      checks prompt by its source.
- [x] 2.4 Add the two enums to the resume event, pass the kind through `dispatch`,
      add `feedback_source` beside `from_person`, and switch the graph's prompt choice
      and the clearing of passed-check feedback to read it.
- [x] 2.5 Update the docs' event table and the changelog.

## 3. [agent-build-kit] [tier1] Outcomes and exceptions are defined values

Done when the unit outcomes, the pause record, the escalation kinds, the unit states and
the unsupported-toolchain exception are enums or types, and the tests that pinned prose
assert on fields.

- [x] 3.1 Test: the graph, the CLI and telemetry record outcomes from one enum; a usage
      pause reaches `pause_for_usage` from its own reason and time fields.
- [x] 3.2 Test: an unrelated `NotImplementedError` in a run fails the unit and is not held
      as toolchain; `ProfileUnsupported` is.
- [x] 3.3 Replace the bare outcome strings and `ESCALATIONS` and the unit state strings
      with `UnitOutcome`, `Escalation` and `UnitState`, add `PauseInfo` to the outcome,
      and add `ProfileUnsupported`.
- [x] 3.4 Rewrite the tests that assert on `held before`, `rework requested`, `tier 1
      failed`, `needs a human` and `base moved before its push` to assert on the cause,
      kind and source fields.
- [x] 3.5 Compare `docs/unit-graph.md` and `docs/architecture.md` with what these groups
      built and change what no longer matches, or say in the pull request that nothing
      differs.
