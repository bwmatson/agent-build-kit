# Design

## Where this goes

The poller keeps a snapshot per pull request and compares it to what the host
reports now. Three comparisons dispatch a rework: a review decision that has just
become changes-requested, a comment or review id that was not there before, and a
check that is failing now and was not before. Each is written as a transition, and
the code says why: reporting a standing state every poll "would rework the unit
every five minutes all night."

Mergeability is a fourth field of the same kind, and it belongs in the same place,
with the same discipline.

## Two states, not one

The host answers mergeability with three possibilities, and conflating two of
them would make this worse than absent:

- **Mergeable.** Nothing to do.
- **Conflicting.** The branch needs a rebase. This is the signal.
- **Unknown.** The host computes mergeability asynchronously and reports that it
  does not know yet — routinely, for a few seconds after any push, which means
  after every one of the pipeline's own pushes.

An unknown answer treated as a conflict would dispatch a rework immediately after
the pipeline pushed a perfectly good branch, on almost every unit. So unknown is
not a signal: it is recorded as unknown, nothing is dispatched, and the next poll
asks again. The transition that matters is *into* a definite conflicting state,
from a state that was not conflicting.

## Why not rebase every open branch when the trunk moves

That is the other way to close this hole, and it is worse.

Most open branches merge cleanly onto a trunk that has moved; rebasing them all
would rewrite their commits for no reason, and a rewritten branch loses its
recorded approval unless the diff comes out identical — so a clean branch that
nobody needed to touch would go back through review. The host's mergeability
answer is the precise signal: it says which branches actually cannot merge, and
only those pay for a rebase and a re-review.

## What the reviewer sees

`abk status` prints what is awaiting review, and that list is what a person works
from. A pull request that cannot be merged is not actionable, so the line says so
rather than looking like the others. This matters more than it sounds: the failure
this change fixes was visible for a whole day as an ordinary queue entry.

## What this does not fix

A unit can still be stale without conflicting — its branch mergeable, its tests
passing against a trunk it has not seen. Nothing here rebases that, and nothing
should: it merges cleanly, and the checks that matter run against the merge
result at merge time.

Nor does this change how a merge's dependents are restacked. That mechanism
handles the units a merge names as children; this handles the ones no merge names
at all.
