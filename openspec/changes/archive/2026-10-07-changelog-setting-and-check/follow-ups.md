## From `changelog-setting-and-check/1`

- In cli/pipeline.py, `build_stack_moves.tier1_of` finds the repo by matching `cwd` against `worktree_root / path.name`, which duplicates the layout in `workspaces.worktree_path`. Consider binding tier 1 by the repo `build_restack` already has, so the two cannot drift.
- src/agent_build_kit/cli/pipeline.py:1294 — `tier1_of` works out the repo again from `cwd`. It does this by matching against the checkout path or `worktree_root / path.name`, which copies the layout in `workspaces.worktree_path`. `build_restack` already knows which repo it is moving (`repo`/`child.repo`), so it could hand that over instead.
