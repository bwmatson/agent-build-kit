# unit-worktrees-are-keyed-by-the-repository-name

A unit's worktree directory is named for the repository's name in `abk.yaml` (`repos.<key>`), not for the last segment of its checkout path, which for a `path: .` repo is the pipeline worktree's own folder and has changed. A worktree already registered for the unit's branch under the worktree root is used where it is, whatever it is keyed by; one anywhere else is refused. `abk doctor` notes worktrees under another key and registered ones whose directory is gone.
