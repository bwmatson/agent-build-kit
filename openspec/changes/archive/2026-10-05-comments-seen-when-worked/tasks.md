# Tasks

Acceptance: none — poller bookkeeping inside the pipeline; tier-1 tests over
the poll and the handlers prove it.

## 1. [agent-build-kit] [tier1] Keep a comment unseen until a unit takes it

Done when a comment left on a held unit's pull request is delivered as a rework
once the unit is released, and no event the handler declined is recorded as
handled.

- [x] 1.1 Test: a poll that finds a new comment on a pull request whose unit is
      held leaves the unit as it was and saves the previous snapshot, so the
      comment is still new on the next poll.
- [x] 1.2 Test: after the unit leaves `held`, the next poll requeues it with the
      reviewer's comment as feedback and records the comment as seen.
- [x] 1.3 Test: a comment on a satisfied unit, or on a pull request with no
      unit, is recorded as seen and requeues nothing.
- [x] 1.4 Test: the "held, ignoring" line is logged once while a comment waits,
      not on every poll.
- [x] 1.5 Make `_requeue` report whether it took the event, return that from
      `on_rework`, and log the wait once per unit and event.
- [x] 1.6 Describe it in `docs/architecture.md` where the poller's deferral is
      explained, and add a changelog entry.
