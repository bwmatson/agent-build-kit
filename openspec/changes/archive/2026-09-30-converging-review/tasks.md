# Tasks

Acceptance: none — this is the pipeline's own review loop, with no surface a
consumer drives; what proves it is tier-1 tests whose reviewer returns each
verdict shape in turn, including the ones that do not exist yet.

## 1. [agent-build-kit] [tier1] Verdicts that let a review finish

Needs: scope-to-this-unit group 1 — this unit's groups are already implemented on its
branch, so every run ends with nothing to commit. Until a unit with nothing left to do is
recorded as satisfied rather than failed, it cannot pass.

Done when a reviewer can defer, escalate a class, escalate a repeated
disagreement, and knows what the last round costs — and when spent rounds leave a
pushed branch and a held unit instead of a discarded one.

- [x] 1.1 Test: the round note carries the round number, how many remain, and
      what running out costs; the final round says it is final.
- [x] 1.2 Test: a verdict that approves with recorded follow-ups approves the
      unit, records the items against the change where a later unit and the pull
      request will see them, and does not spend another round.
- [x] 1.3 Test: a verdict that tries to defer a correctness problem, a test that
      would pass either way, a missing test the task asked for, or something the
      command policy forbids is treated as blocking, not as a follow-up.
- [x] 1.4 Test: a verdict reporting that successive rounds are finding instances
      of an open-ended class holds the unit with that reasoning recorded, and a
      point raised again after the builder declined it with a reason holds the
      unit with both positions recorded.
- [x] 1.5 Test: when the rounds run out with blocking points, the branch is
      pushed, the points reach the pull request body, the unit is held, and
      nothing is recorded as approved or merged.
- [x] 1.6 Extend the verdict the loop parses with the deferral and the two
      escalations, keeping the existing shape valid so a reviewer that answers as
      it does today still works.
- [x] 1.7 Tell the reviewer the budget and the stake in the round note, and tell
      it in the review prompt what may and may not be deferred, when to escalate
      a class, and when to escalate a disagreement.
- [x] 1.8 Replace the last round's discard with push, report and hold, and record
      follow-ups where the change keeps them.
- [x] 1.9 Update `docs/architecture.md` where the review loop is described, and
      note in the `abk-pipeline` skill that a held unit may now mean an
      unenumerable problem or a disagreement, with the record saying which.
