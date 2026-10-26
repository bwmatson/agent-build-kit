# a-conflict-is-resolved-in-one-session-without-holding-the-repo-lock

A restack conflict is now settled by one agent session that works from the smallest change to the largest, instead of a resolver run
followed, when it fails, by a second run from a reset branch. The first prompt states the order: change only the conflicting hunks and
the files that conflict; widen to the unit's other files that depend on the conflict when the pipeline's checks fail; port the old work
onto the new base only when that cannot work. The session is the unit's build session, so what the agent learned on the first rung is
there on the next. And the repository's turn, the lock every worktree add and push waits for, is held only around the git commands that
write shared state, not for the minutes the agent edits files. A unit with no worktree gets a temporary one, so the operator's checkout
is never switched.
