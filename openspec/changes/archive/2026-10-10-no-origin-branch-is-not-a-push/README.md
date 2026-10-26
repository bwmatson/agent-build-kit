# no-origin-branch-is-not-a-push

The agent-pushed guard fails any agent step that moves the unit's branch "on the remote". In a repo
with no `origin` there is no remote, so the guard reads the worktree's own branch and mistakes a
legitimate commit for a push. The guard is skipped when there is no `origin`.
