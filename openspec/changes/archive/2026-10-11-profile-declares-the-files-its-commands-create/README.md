# profile-declares-the-files-its-commands-create

The toolchain profile can say which files its own commands create or rewrite in a unit's worktree, and those
files become the pipeline's own, like an environment's lock files: they no longer hold the unit as uncommitted
work, are never discarded, and an untracked one is never committed. This covers a repository with no
`environment` section, which `environment-sync-leaves-no-leftovers` could not, because it takes its paths from
that section.
