# Proposal

## Why

The acceptance tests that build a unit through a real agent start from `scratch_app` (`tests/factories.py` in
the agent-build-kit repository): a python-uv app whose `.gitignore` lists `__pycache__/`, `*.pyc` and `.venv/`,
with no `uv.lock` committed or ignored, and a scratch `abk.yaml` with no `environment` section. The first
`uv run` in a unit's worktree, whether the pipeline's tier-1 commands or the agent's own, creates an untracked
`uv.lock`. The next step asks for the worktree, the dirty check (`prepare_worktree`, `DirtyWorktree`, which
counts untracked files through `_porcelain`) finds it, and the unit is held: "uncommitted changes in the
worktree: uv.lock". A test that needs a second step (a rework, a tick after a review comment) then fails; in
`test_graph_acp_unit.py` the failing line is the `len(second) > len(first)` check of the rework test (`assert
2 > 2`). `ui-chat-editing/5` failed 11 of 25 tier-2 tests on 2026-10-10 for this reason.

The merged change `environment-sync-leaves-no-leftovers` makes the lock paths named in a repository's
`environment.inputs.lock` pipeline-owned. The scratch app has no environment section, so it does not apply.
The framework-level fix, a hook in the language profile, is a separate change. This change fixes the fixture.

## What Changes

- **The scratch app ignores `uv.lock`:** its `.gitignore` gains the line `uv.lock`. It is ignored rather than
  committed because resolving a lock needs the package index, and the fixture must build where there is no
  network.
- **A tier-1 test pins it:** it runs the fixture's tier-1 commands, the ones the python profile produces, and
  asserts that git reports no change in the worktree afterwards.

## Impact

- Capability: `test-coverage` (added requirement).
- Code: the scratch app fixture and one tier-1 test. No framework code.
- Open question, not answered here: why these tests passed before 2026-10-09 about 16:00 UTC. No cause is
  claimed.
