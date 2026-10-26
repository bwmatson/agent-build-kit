# Tasks

Acceptance: none — this is the adapt step's own accounting, with no surface a consumer drives;
tier-1 tests over a replay and an incomplete answer prove it.

## 1. [agent-build-kit] [tier1] Account for what changed, and ask again before failing

Done when the adapt step asks only about tests that are missing or changed, an incomplete
accounting is put back to the agent before the unit fails, and every existing guard still holds.

- [x] 1.1 Test: a test present and unchanged after the replay needs no decision and its absence
      from the accounting is not a problem; a missing test and a changed test each still require
      one.
- [x] 1.2 Test: an accounting missing one required decision results in the agent being asked
      again with that name, and the unit proceeding when the answer completes it — without the
      ported code being rebuilt.
- [x] 1.3 Test: an accounting still incomplete after the last attempt fails the unit, with the
      outstanding problems recorded on the unit.
- [x] 1.4 Test: a keep for a test not in the tree, and a retirement without a reason, are still
      problems.
- [x] 1.5 Narrow what the adapt prompt asks for to the missing and changed tests, computed from
      the old ref and the tree rather than requested.
- [x] 1.6 Put the check's problems back to the agent, bounded, before failing; record them on
      the unit when it does fail.
- [x] 1.7 Say in `docs/architecture.md` where the restack and adapt step are described that the
      accounting covers what the replay changed, and that an incomplete answer is asked again.
