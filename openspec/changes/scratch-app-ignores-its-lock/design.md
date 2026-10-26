# Design

## What is verified

- `scratch_app` writes the `.gitignore` as `__pycache__/\n*.pyc\n.venv/\n`, commits `pyproject.toml`
  (dev group `pytest`, `pre-commit`), a local `.pre-commit-<redacted>` and a source and tests folder. No lock
  is written, committed or ignored.
- Reproduced: building the fixture, adding a test, committing it, and running `profile.lint_command("HEAD~1")`
  and `profile.test_commands(app, [...], root_extras=[])` for the `python-uv` profile (the commands
  `test_scratch_app_unit_test.py` already runs) exits 0 for each and leaves `?? uv.lock` in `git status --porcelain
  --untracked-files=all`. The same holds with `UV_OFFLINE=1` on this machine, because the packages are in uv's
  cache.
- The existing `test_scratch_app_unit_test.py` asserts only exit codes, so it passes while the worktree is dirty.
- Callers of `scratch_app`: `test_graph_acp_unit.py`, `test_acp_build_unit.py` and `test_telemetry_stack.py`
  on main, plus `test_chat_editing_acp.py` (branch `spec/ui-chat-editing/5`) and `test_local_forge_unit.py`
  (branch `spec/local-forge/3`), which are not on main yet. No test reads a lock: nothing in the repository's
  tests under `tests/` expects a `uv.lock` in the scratch app.
- Correction to the brief: on main, `test_chat_editing_acp.py` and `test_local_forge_unit.py` do not exist; they
  are in unit worktrees. The fix to the fixture reaches them when they rebase on main.

## Options

**(a) Ignore `uv.lock` in the fixture's `.gitignore`.** One line; the worktree is clean to git, the lock stays
on disk so the next `uv run` reuses it, and the dirty check, which reads git's view, never sees it.

**(b) Commit a `uv.lock` in the fixture.** Rejected: a lock is produced by resolving against the index, so the
fixture would need the network when it is made, or a lock checked in as a binary-sized fixture that drifts from
`pyproject.toml`. An ignored file costs nothing and needs no resolution up front.

**(c) Give the scratch `abk.yaml` an `environment` section naming the lock.** Rejected here: it makes the
fixture depend on the sync feature to hide a fixture defect, and the section would have to be kept in step with
the profile. The framework-level handling is the separate profile-hook change.

Chosen: (a).

## The test

The test sits beside `test_scratch_app_unit_test.py` in the same tier-1 file or a new file in the same folder. It
runs the same commands the python profile gives for the fixture (lint, then the tests), then asserts that the
porcelain status with untracked files listed is empty, and that `uv.lock` is present in the worktree (so the
test would catch the lock being absent only because the commands did not run). Run before the fixture change it
fails naming `uv.lock`.

UNVERIFIED: that the commands pass with no network and a cold uv cache. They resolve `pytest` and `pre-commit`
from the index, and a cold cache with no network fails them, before any assertion about git. The builder must
run the test with the cache warm (as on this machine) and, if the test is to run without the network, say so
in its skip condition the way `test_scratch_app_unit_test.py` skips when `uv` is missing; it must not weaken the
assertion to make a cold offline run pass.

## Open question

Why the tests passed before 2026-10-09 about 16:00 UTC is unknown. Nothing here depends on the answer, and
no cause is claimed.
