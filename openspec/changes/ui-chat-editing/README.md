# ui-chat-editing

Editing from a chat in the web UI. An agent changes a unit's worktree live and nothing is committed until
the user commits; the commit is adopted into the unit's normal checks and review; the tick tells those
changes from a failed run's leftovers; and sessions that are not the unit's build session can change
code and specs together.
