# Tasks

Acceptance: none — poller and event handling inside the pipeline; tier-1 tests
over the poll diff, the handler and the store prove it.

## 1. [agent-build-kit] [tier1] The hold label coming off releases the unit

Done when removing `agent-hold` from a pull request returns a unit that label
held to waiting for review, leaves every other kind of hold alone, and loses
nothing that happened during the hold.

- [x] 1.1 Test: a snapshot diff in which `agent-hold` is in the previous
      labels and not the current ones dispatches `release`; one in which it is
      still there, or was never there, does not; the first poll of a pull
      request records only.
- [x] 1.2 Test: a unit held by the label is returned to `in_review` and its
      thread resumed with a release; the log says so.
- [x] 1.3 Test: a unit held by the review loop, a depth cap or the toolchain
      stays held and the log names the reason; a stored unit with no recorded
      cause whose last note says "held by a reviewer" is released, and one with
      neither is left held.
- [x] 1.4 Test: a comment or a failing check that arrived during the hold is
      delivered by the next poll after the release; a release for a unit being
      built is deferred and reported again.
- [x] 1.5 Record the cause of a hold on the stored unit (`held_by`, absent in
      older records), add the `release` event to the poller and the handler to
      `events`, and return the pipeline's state label to `in-review`.
- [x] 1.6 Update the abk-pipeline skill's held section, `docs/architecture.md`
      and `docs/unit-graph.md` event tables, and the changelog.
