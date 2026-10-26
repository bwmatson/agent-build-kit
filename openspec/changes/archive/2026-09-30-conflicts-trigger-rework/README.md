# conflicts-trigger-rework

Notice when a unit's branch can no longer be merged, and send it back for a
rebase — the way a failing check or a review comment already does.

A conflicted branch is invisible to the poller today: mergeability is not among
the fields it asks for, and a restack only fires for the dependents of a unit that
just merged. So a unit whose dependency merged this morning sits in the review
queue all day, unmergeable, looking healthy, until a person notices.
