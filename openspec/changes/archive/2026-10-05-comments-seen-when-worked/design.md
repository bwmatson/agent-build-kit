# Design

## The seam that exists

`PrPoller.poll` already keeps `known[number]` instead of the new snapshot when
a dispatch returns `False` (the unit is being built; `events._deferred`). The
change makes the handler for a held unit answer `False` too, so a comment on
a held unit is kept for the next poll the way a busy unit's is.

## on_rework

`_requeue` returns whether it took the event. For a `HELD` unit it returns
`False` (not taken), and `on_rework` returns that. For `SATISFIED` and for no
unit it keeps returning `True` (nothing will ever take it).

## What is retained

Retaining the previous snapshot keeps every difference in it, not only the
comment: a label added, a check that turned red, the head. Each of those is
reported again on later polls, which is what `_deferred` already does for a
busy unit, and each is handled by the same rules when the unit is released
(a stale failing check is re-evaluated against the current checks, the head
against the branch). The rework label is the one consumable the poller removes
after acting; a held unit leaves it in place until it is taken.

## Noise

The "held, ignoring" log line repeats every poll while a comment waits. It is
logged once per unit and event kind until the snapshot moves on.

## Feedback overwrites

`set_feedback` replaces what a unit already waits on. A comment arriving for a
unit that is `planned` with other feedback replaces it. That is a separate
problem; this change does not widen it, and a note for it goes in follow-ups.
