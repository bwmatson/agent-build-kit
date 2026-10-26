# Tasks

Acceptance: none — this is the poller's own trigger list, with no surface a
consumer drives; what proves it is tier-1 tests over recorded host answers,
including the undetermined one.

## 1. [agent-build-kit] [tier1] A branch that cannot be merged is sent back

Done when a pull request that becomes unmergeable is reworked once, an
undetermined answer dispatches nothing, and the review queue says which entries
cannot be merged.

- [x] 1.1 Test: mergeability is among the fields the forge asks the host for and
      is carried on the polled pull request.
- [x] 1.2 Test: a pull request that was mergeable and is now conflicting
      dispatches exactly one rework, with a reason naming the conflict; polled
      again while still conflicting it dispatches nothing.
- [x] 1.3 Test: an undetermined answer dispatches nothing, is not recorded as a
      conflict, and a later mergeable answer leaves the unit untouched; an
      undetermined answer followed by a conflicting one dispatches once.
- [x] 1.4 Test: the status output marks an unmergeable pull request awaiting
      review, and leaves a mergeable one as it reads today.
- [x] 1.5 Add the field to the poll, the transition to the poller's triggers
      beside the failing-checks one, and the mark to the status line.
- [x] 1.6 Say in `docs/architecture.md`, where the poller's triggers are listed,
      that a conflict is one of them, and note in the `abk-pipeline` skill that a
      unit can go back to planned because its branch stopped being mergeable.
