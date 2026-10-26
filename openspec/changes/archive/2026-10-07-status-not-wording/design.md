# Design

## Cause

`Cause(StrEnum)` in the unit store module: `rework`, `base_changed`, `upstream_went_back`,
`usage`, `depth`, `toolchain`, `review_escalated_class`, `review_escalated_disagreement`,
`needs_human`, `requeued`, `released`, `restack_conflict`, `restack_deferred`, `merged`,
`closed`, `failed`. `set_state(..., cause=)` writes it on the history entry; entries
without one load as `None`. `HeldBy` stays for who owns a hold (label, review, depth,
toolchain); `cause` says why the state changed. The graph's hold and boundary paths, the
poller's rework handler, the requeue command and the restack handlers each pass the
cause they know. `base_moved` and `upstream_incomplete` return `(Cause, text)`.

## `_sent_back`

`last.cause in {REWORK, BASE_CHANGED}` and `at > started`. The skip is logged with the
cause so an idle slot has a visible reason. `held_for_base` and the "held before" prefix
checks are deleted. `effective_state` (the diagram) reads `cause` too.

## Resume events

`ResumeEvent` gains `requeue: RequeueReason | None` and `rework: ReworkKind | None`;
`reason` stays as display text. `on_rework` takes the kind from the poller, which passes it
through `dispatch`. The feedback for a rework is chosen by kind: failing checks get the CI
log only, a conflict gets the restack instructions, the others get the reviewer's words.

## Feedback source

`StoredUnit.feedback_source` (`FeedbackSource` enum) set by `set_feedback`; the graph's
failed-check path and the clearing after passing checks read it. The `TIER1_FAILED`
prefix stays in the text for people and is no longer parsed.

## Depth hold

`StoredUnit.held_base` is written with the depth hold and read by the restore path; the
regex over the note is deleted.

## Outcomes

`UnitOutcome(StrEnum)`: the `RunStatus` members plus interrupted, rate limited, skipped,
error. `RunOutcome` gains `pause: PauseInfo(reason, until)`; the CLI passes that to the
usage pause. `Escalation` replaces `ESCALATIONS`; `UnitState` replaces the state strings.
`ProfileUnsupported` is raised by the profile code where it raised `NotImplementedError`,
and only it is held as a toolchain problem.

## No migration

Nothing derives a cause from a note, ever. A history entry written before causes existed
loads with `cause=None`; the pass never readmits such a unit mid-pass (the next pass picks
it up, as today), the diagram shows it by its state, and `held_by` and `held_base` read as
absent for it. The old matchers are deleted with the code that used them.

Units still in flight at cutover are dealt with once, by hand, with the commands that
already write real values: the group's last task lists every unit that is `planned` or
`held` with no cause, and each is requeued (`abk requeue`) or, for a reviewer hold, held
again from the pull request, so the entry that follows carries a cause, `held_by` and
`held_base` from the event.

## Tests

A table-driven test drives every hold path of the graph's rebase and boundary nodes and
asserts the cause recorded and that `_sent_back` counts exactly the rework and
base-changed ones. The tests that assert on prose (`held before`, `rework requested`,
`tier 1 failed`, `needs a human`, `base moved before its push`) assert on the fields.

## Out of scope

Text from external tools (`external-text-contract-tests`), and display wording.
