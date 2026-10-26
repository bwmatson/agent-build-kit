# Tasks

Acceptance: none — the fixture is a real git repo and the commands real child processes, so a unit-test test proves it.

Priority: 1

## 1. [agent-build-kit] [unit-test] The scratch app's worktree stays clean under its own tier-1 commands

Done when running the scratch app's tier-1 commands leaves nothing for git to report, so a unit built in it
is not held for an uncommitted lock at its next step.

- [x] 1.1 Test: build the scratch app, add and commit a test, run the python profile's lint command and test
      commands for it, and assert each exits 0 and that `git status --porcelain --untracked-files=all` is
      empty afterwards while `uv.lock` exists in the worktree. It fails before 1.2, naming `uv.lock`. Mark it
      like `test_scratch_app_unit_test.py` (integration, skipped without `uv`); UNVERIFIED offline, see design.md.
- [x] 1.2 Add `uv.lock` to the scratch app's `.gitignore` in `tests/factories.py`, and extend its docstring to
      say the lock is ignored because resolving it needs the network.
- [x] 1.3 Run the integration tests that build a unit through the scratch app (`test_graph_acp_unit.py`,
      `test_acp_build_unit.py`) with their agent configured, and report whether the rework step is reached.
