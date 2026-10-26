# Proposal

## Why

The poller diffs each pull request against the snapshot it saved last time and
dispatches an event for what is new. It saves the new snapshot, comment ids
included, unless the handler answers that the event was deferred (`False`), in
which case the old snapshot stays and the next poll reports it again. Only a
unit being built answers that way.

`_requeue` for a **held** unit logs "held, ignoring" and returns as handled. The
poller therefore records the comment as seen. A reviewer's inline note left
while the unit was held or being reworked on a person's behalf is gone for good:
the unit's saved feedback never held it, no later poll reports it, and when the
unit is requeued no one is told. A `StrEnum` request on a unit's pull request
was lost this way and sat unanswered for days.

Holding a unit should stop the pipeline touching it, not discard what reviewers
say about it.

## What Changes

- **A comment on a held unit is not recorded as seen.** The rework event for a
  held unit is reported as not taken, so the poller keeps the previous
  snapshot and reports the same comment again on later polls.
- **It is delivered when the unit is released.** Once the unit leaves `held`,
  the next poll dispatches the comment as a rework with the reviewer's words,
  as it would have if the unit had been waiting in review.
- **Other deliberate non-actions stay consumed.** A satisfied unit (its pull
  request is closing) and a pull request with no recorded unit still discard the
  event: there is nothing for the comment to be worked on by.
- **The log says it is waiting**, once per hold, not every poll.
