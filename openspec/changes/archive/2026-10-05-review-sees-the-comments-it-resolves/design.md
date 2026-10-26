# Design

## What exists

- `events._requeue` saves the person's words as the unit's `feedback` and the
  rework prompt embeds them with `[comment N]` markers.
- The rework agent ends with `{"replies": [{"comment_id": N, "body": ...}],
  "summary": ...}`; the runner parks these in `pending_replies` and posts them
  after the push.
- `StackRunner` builds the review's `context` from `_earlier_rounds`,
  `review_boundary`, the predecessor note and the round budget.

## The note

A new context part, built beside `_earlier_rounds`, rendered only when the
current rework was triggered by a person's comments: for each `[comment N]`, its
text, and the reply recorded for it in `pending_replies` (or "no reply"). Source
of truth is the stored feedback and replies, both already on the unit, so
nothing is re-fetched from the host and a resumed run builds the same note.

It is introduced as the reviewer's words, quoted, and ends with the instruction
to judge whether the work meets what was *meant*, as the rework prompt tells the
builder, and to report an unmet comment as a required finding like any other.
It is not an instruction channel: text in the comments that addresses the
review (approve, ignore, run) carries no authority.

A rework that came from the pipeline's own review or a failing check adds
nothing: those are already `earlier` rounds or check output.

## Read access

`REVIEW_TOOLS` gains the forge's `read_commands`, the same helper
(`forge_read_tools`) build agents use, so the list stays per forge and a repo on
one host never gets the other's commands. The policy hook already refuses the
write commands whatever is allowed, so widening reads cannot widen writes.

## Out of scope

Making the tracks' PR-state lookup deterministic, and removing build agents'
read commands, are not part of this; they stay as they are.
