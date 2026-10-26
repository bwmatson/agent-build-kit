# Proposal

## Why

`agent-hold` is documented as the way a person takes a unit over: "it stays
until a person removes it". The poller turns the label being **added** into a
`hold` event and the unit goes to `held`. Nothing reads the label being
**removed**: the snapshot diff looks only at labels added. Two units held that
way stayed `held` for about two hours after the label came off, with the
pipeline reporting nothing to do, and were freed only by an explicit
`abk requeue`.

The abk-pipeline skill tells a person to "remove the label and comment what
should change; the next poll picks either up". The comment half works. The
label half does not: removing the label alone is the natural way to hand a unit
back, and it is silently ignored.

A removal cannot simply requeue a held unit: a unit is also held by the review
loop itself, by a stack depth cap, or because the toolchain cannot build it, and
none of those has anything to do with the label.

## What Changes

- **A label removal is an event.** The poller reports `agent-hold` leaving a
  pull request as `release`, from the snapshot diff, as it reports it arriving
  as `hold`.
- **Only a hold the label caused is released.** The unit records why it was held
  (a reviewer's label, the review loop, a depth cap, the toolchain). A release
  frees the first kind and leaves the others held, saying so in the log.
- **A released unit goes back to waiting for review.** Its pull request is open
  and its branch is as it was left: it returns to `in_review`, and the next
  poll delivers whatever arrived meanwhile (a comment, a failing check, a
  cancelled check) through the usual events, with comments that came in during
  the hold still new.
- **The log and the pull request say so.** The unit's log notes the release, and
  the pipeline's own state label returns from `held` to `in-review`.
- **A release that cannot be applied is retried, not lost.** A unit being built
  defers the event, as the other label events do.
