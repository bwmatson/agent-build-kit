# Design

## One gate, enforced wherever a unit would start or resume

The gate already exists as `merge_before` on the unit, recomputed from `tasks.md` every tick; what is
missing is that only `planned` units consult it. The check moves to the points where a started unit
re-enters the run: the requeue command and the pass's readmission. Both ask the same question as
the scheduler (`waiting_on`), so there is one definition of "unmet".

## Requeue of a gated unit

`abk requeue` on a `failed` or `held` unit with an unmet gate does not deliver the resume event.
It sets the unit to `planned`, cause `gated`, leaves the thread, branch, session and saved feedback
untouched, records the requested mode (`--rework`, `--restart` or the default resume) and prints the
unmet dependency. When the dependency has merged, the pass lets the unit back in — a `gated` unit is
readmitted by the gate clearing, not by being sent back — and delivers the recorded mode. The
requeue is therefore a statement of intent that waits, not a request refused: the operator does not
have to come back.

## A running or in-review unit

A step already running is never interrupted. `link_needs` writes the gate and logs once ("<unit>:
now waits for <change> group <n> to merge"). An `in_review` unit sent back for rework is checked at
readmission and parks as `gated` the same way.

## Bases and upstream state

`merge_before` edges are not stacking edges. Today a new same-repo `depends_on` written for a
`merged` need can change `base_of` (when the dependency is in review) or make `upstream_incomplete`
send a running unit back. A merge-gated edge is excluded from both, because the unit builds on the
trunk and is only held until the dependency lands.

## Not re-planned

`specification()` already strips `Needs:` lines before hashing, so a Needs-only edit is applied by
`link_needs` the next tick with no planner call. The spec states it so a later change to the hash
cannot quietly make a gate edit re-plan a change and re-claim groups already built.
