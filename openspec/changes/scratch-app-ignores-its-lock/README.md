# scratch-app-ignores-its-lock

The scratch app the acceptance tests build a unit in ignores `uv.lock`, so the lock the first `uv run`
creates in a unit's worktree no longer holds the unit at its next step; a tier-1 test pins that the
fixture's own tier-1 commands leave its worktree clean as far as git is concerned.
