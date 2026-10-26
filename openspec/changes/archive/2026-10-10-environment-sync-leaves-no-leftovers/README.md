# environment-sync-leaves-no-leftovers

The lock files a repository's own environment `sync` writes in a unit's worktree belong to the pipeline: they no
longer hold the unit as uncommitted work, a lock the unit changed with its dependencies is committed with that
change, and one the sync merely created or reformatted is never committed.
