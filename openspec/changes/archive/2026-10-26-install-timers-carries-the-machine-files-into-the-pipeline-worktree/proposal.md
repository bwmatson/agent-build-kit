# Proposal

## Why

With `planning.publish` / in-repo planning, `abk install-timers` makes a detached worktree of the default branch (`timers.py:515-530`, called from `install_in_repo`, `timers.py:567-586`) and writes units whose `WorkingDirectory` is that worktree (`templates/systemd/abk-tick.service:18`). A worktree is a checkout of tracked files, and the three files that carry a machine's facts are all ignored (`templates/gitignore`: `.env`, `abk.local.yaml`, `scrub.local`), so none is there:

- `abk.local.yaml` is read from beside `abk.yaml` (`config.py:1872-1887`). Without it the worktree loads with `planning.worktree_root` unset (so unit worktrees would be made under the data directory and the existing worktrees and sessions are orphaned, `installation.py:71-73`), usage limits and models at their defaults, and no `verify.env` lookups.
- `.env`: `ABK_` settings fall back to the working copy's file (`installation.py:52-60`), but a `from: env-file` provider with `file: .env` is read relative to the process directory (`installation.py:244`, no root joined), which under the unit is the worktree, so tokens and per-machine values resolve to nothing.
- `scrub.local` is read from the planning root (`scrub_terms.py:56`), so the words that must never be public are not scrubbed.

`abk doctor` run in the worktree reports none of this: its public-content check skips a local file that does not exist (`doctor.py:925-927`) and `_pipeline_worktree` only asks whether the directory exists (`doctor.py:478-494`). A person had to symlink the three files by hand, and would have to again on every new machine.

## What Changes

- **`abk install-timers` carries the machine files** from the working copy into the pipeline worktree as symbolic links, for a working copy or the worktree as the place it is run from. A file the working copy lacks is skipped; a worktree path that is a different regular file (or a link to something else) is refused and named, with nothing overwritten; a repeat run changes nothing, and repoints a dangling link. A file git would not ignore in the worktree is refused too, so a carried secret cannot be staged.
- **The file set has one source of truth**, a constant listing `.env`, `abk.local.yaml` and `scrub.local`, which the carrying, `abk doctor`'s public-content check and `abk config --migrate`'s ignore step all read, replacing the literals at `doctor.py:925` and `config_migrate_write.py:26`.
- **`abk doctor` fails** when the installation is live in a pipeline worktree and a machine file that exists in the working copy is missing, dangling or different there, naming the file and `abk install-timers`; it warns when the working copy has none of the three (a machine not set up yet), naming what to create.
- **Docs**: the move runbook's install step, `docs/init.md`, `docs/configuration.md` ("Where an installation's facts live" and the roles paragraph) and the changelog.

## Impact

- Capability: `pipeline-worktree-machine-files` (new).
- agent-build-kit: a new `machine_files.py`, `timers.py` (`install_in_repo`), `cli/init.py` (the install-timers output), `cli/doctor.py`, `config_migrate_write.py`, `tests/`, `docs/`, `CHANGELOG.md`.
- Not in this change: a tracked copy of any of the files (they stay untracked on every branch); other ignored files (`*.pre-redact` copies, state-directory scratch); creating the files on a machine that has none; moving them when the working copy moves (a re-run of `install-timers` repoints the links).
