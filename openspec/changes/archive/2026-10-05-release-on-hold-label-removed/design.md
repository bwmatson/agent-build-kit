# Design

## The event

`PrPoller._dispatch_changes` computes `labels_added` from the previous and the
current snapshot. It gains `labels_removed` the same way. When `agent-hold` is in
it (and not also just added), the poller dispatches `release`. A first poll of
a pull request records only, as for every event.

## Why a reason on the hold

`on_hold` sets `HELD` with no cause. Other paths set it too, with a history
note. The store records a `held_by` value beside the state: `reviewer` (the
label), `review` (the loop's own), `depth`, `toolchain`. It is set when the
state becomes `held` and cleared when it leaves. Stored units without it load
unchanged and are treated as `reviewer`-held only if their last history note
says "held by a reviewer", which is what the label handler writes.

## The handler

`on_release(pr)`:
- no unit, or the unit is not `held`: log and return handled;
- `held_by` is not `reviewer`: log "the hold on #N was not the label's; it stays
  held" and return handled, so a depth or toolchain hold is not undone by an
  unrelated label edit;
- otherwise, under the unit's claim, return it to `in_review` (resuming its
  thread with a `release` event on the graph engine) and log it.

A unit whose branch is being built defers the event, as `on_hold` does.

## What the next poll delivers

Releasing does not rework the unit: it puts it back where a unit waiting for
review is, and the poller's diff then reports anything new. Comments, checks
and cancelled checks that arrived during the hold are still new to it: the hold
already keeps a comment arriving with the label unrecorded, and a unit held for
a long time should not have swallowed what happened meanwhile. If a comment has
already been seen under a hold, it is not re-delivered.

## Documents

The abk-pipeline skill's held section and `docs/architecture.md` and
`docs/unit-graph.md` event tables say a removal releases a reviewer's hold, and
that other holds are released by their own means.

## Out of scope

Releasing a hold by any other signal (a comment, a command), and adding a
requeue path for the review loop's own holds.
