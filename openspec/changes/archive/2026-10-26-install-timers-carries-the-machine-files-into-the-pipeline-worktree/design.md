# Design

## What was checked, and where

Read-only: `git fetch`, then `git show origin/main:<path>` in the build tool's checkout (origin/main at `37156de0`). Paths are under `src/agent_build_kit/`; the line numbers were read on that commit.

- **How the worktree is made and refreshed.** `install_in_repo` (`timers.py:543-602`) picks the worktree (the marker's, else `<data dir>/<repo>/planning`), makes it with `git worktree add --detach` (`_make_worktree`, 515-530), moves it to the tip (`_bring_to_tip`, 533-540, which only looks at tracked changes: `--untracked-files=no`), then writes the units for it (598). Its output is printed by `cmd_install_timers` (`cli/init.py:883-960`); a `PlanningWorktreeRefused` is one stderr line and exit 1 (922-924). Every later refresh is `_sync_worktree` (`pipeline/planning_sync.py:186-221`): `git merge --ff-only`. Its docstring says "Nothing is stashed, reset or deleted" (225). There is no `git clean` and no checkout of the whole tree anywhere, so an untracked or ignored file survives. The one deleting step, `_clear_landed_files` (165-183), removes an untracked file only when an incoming commit adds the same path with the same bytes, which is the case of someone committing a machine file, already a doctor warning (`doctor.py:928-935`).
- **How each file is found.**
  - `abk.local.yaml`: `overlay_path(path)` is `path.with_name(...)` (`config.py:1872-1874`), read with `read_text` (1860), which follows a link. `loaded_files` in the sandbox policy grants `path.resolve()` (`sandboxes/policy.py:66-70`), so a link grants the target; the write-deny list resolves too (`policy.py:287-296`).
  - `scrub.local`: `installation.root / "scrub.local"`, `read_text` (`scrub_terms.py:28,56`); a link works.
  - `.env`: `env_file_for` (`installation.py:52-60`) reads the working copy's `.env` for `ABK_` settings when the worktree has none, but `_resolve` reads an `env-file` provider's `file` as given (`installation.py:244`), a relative `.env` against the process directory, which is the worktree under a unit. The worktree needs its own `.env`.
- **The configuration fence** (`pipeline/config_guard.py:27-37, 81-91`) reads both configuration files with `read_bytes` before and after a confined step and compares the bytes. A link is read through, so an edit made in the working copy while a run is in progress is seen by the fence as it is for an edit in place (a person's change, which is what the fence is for).
- **The existing lists of machine files.** `templates/gitignore` (`.env`, `abk.local.yaml`, `scrub.local`, `*.pre-redact`), `LOCAL_IGNORES` (`init/scaffold.py:641`: overlay, `scrub.local`, the redaction copies), `IGNORED_LOCAL_FILES` (`config_migrate_write.py:26`: overlay, `scrub.local`) and the literal pair in `_local_files` (`doctor.py:925`). None lists `.env`, and none is the whole set; the redaction copies are not configuration.
- **Tests available** (`tests/`): `planning_worktree_support.in_repo` / `working_copy_of` (real git, a bare origin, a working copy and a worktree with its marker), `cli/test_install_timers_in_repo.py` (a `working_copy` fixture with a temporary home and unit directory, `main(["install-timers"])`), `cli/in_repo_doctor.py` (`in_repo`, `with_pipeline_worktree`, `checks_of`, `named`).

## Decisions

### Link, not copy

A copy would be a second source: a limit changed in the working copy's `abk.local.yaml`, a token rotated in `.env`, a word added to `scrub.local` would not reach the ticks until someone re-ran `install-timers`, and the file in the worktree would drift without a signal. A symbolic link has one source and every reader above follows it (`read_text`, `read_bytes`, `resolve()`). The costs: a link breaks when the working copy moves, which `install-timers` repairs and `abk doctor` reports; and a writer that replaces a file by rename in the worktree (`abk config --migrate` run there, `config_migrate_write.py:130-137`) replaces the link with a regular file, which `abk doctor` then reports as different. Both leave the data safe, and neither is silent. Git treats a link at an ignored path as ignored (the patterns have no trailing slash), so the worktree stays clean; the carrying checks `git check-ignore` in the worktree and refuses a file that would show up untracked, rather than leave a secret one `git add -A` from being committed.

The link is absolute, to the working copy's path as written, because the two trees are in different places (the worktree is under the data directory).

### The file set is one constant

`MACHINE_FILES = (".env", OVERLAY_FILENAME, LOCAL_LIST)` in a new `machine_files.py`, with the carrying and the checking. `doctor._local_files` and `config_migrate_write.IGNORED_LOCAL_FILES` read it for the two names they list now (the migration does not need `.env` ignored: it is in the packaged ignore block; so it filters to the names it writes) rather than keep literals. `*.pre-redact` stays out: those are copies a command leaves beside what it rewrites, anywhere, not configuration the ticks read.

### What carrying does, by case

For each name in the set, `source` being the working copy (the root, or `main_working_tree` when run from the worktree) and `target` the worktree's path:

| Working copy | Worktree path | Result |
|---|---|---|
| has no file | anything | skipped (nothing to carry); no error |
| has it | missing | link made |
| has it | link resolving to the same file | `unchanged` |
| has it | dangling link | repointed (a dangling link holds no data) |
| has it | link to another existing file | refused, named |
| has it | regular file, same bytes | `unchanged` (a copy someone made; the doctor still passes it) |
| has it | regular file, different bytes | refused, named, never overwritten |
| has it | not ignored by git in the worktree (or tracked) | refused, named, with the `.gitignore` or `git rm --cached` step |

All refusals are found before anything is written (no half-linked set), and any refusal is the same stderr line and exit 1 as `PlanningWorktreeRefused`, before the units are written: units that tick on defaults are what this change prevents. The worktree made and the marker written stay, so a re-run after the fix continues. `--dry-run` prints `would link` and writes nothing. `--remove` leaves the worktree and its links, as it leaves the worktree. When run from the worktree with no locatable working copy (`main_working_tree` is None: a bare layout) nothing is carried and a note says why.

### The doctor fails on a missing file and warns on an absent set

`abk doctor` has a `machine files` check in an in-repo installation that is live in a pipeline worktree (from the working copy via the marker, from the worktree via `main_working_tree`). For each name the working copy has: it passes when the worktree path resolves to the same file or holds the same bytes; it FAILS when the path is missing, dangling or different, naming the file and `abk install-timers`. A file the working copy does not have is not reported, because each of the three is optional on its own. When the working copy has none of the three, one warning: nothing to carry, the pipeline runs on defaults, and it names `abk.local.yaml` (paths, worktree root, limits), `.env` (copy `.env.example`) and `scrub.local`. That is the second-clone and fresh-machine case: the worktree gets nothing, and the doctor says so rather than staying silent. A separate planning repo, or an in-repo installation with no live worktree, has no such check.

## Risks

- A person who symlinked the files by hand already has the same links: `unchanged`.
- Linking `.env` into a tree an agent can read: the sandbox never grants `.env` (`policy.py:61-65`) and a confined step's environment is stripped; the worktree path adds no grant. The builder pins this with a test that `loaded_files` is unchanged by the link.
- The kit is public: tests and docs use neutral names (`app`, `example`) and temporary directories only.
