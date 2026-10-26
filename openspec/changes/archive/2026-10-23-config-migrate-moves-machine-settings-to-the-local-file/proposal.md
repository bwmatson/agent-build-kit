## Why

Code at agent-build-kit `origin/main` (74a22e4a).

`abk config --migrate` (`cmd_migrate`, `src/agent_build_kit/cli/config_cmd.py:30-73`) reads the one abk.yaml in force, runs `migrate(text, runtime)`
(`config_migrate.py:144-152`: `_move_ceiling`, `_move_limits`, `_rename_test_kind_keys`, `_move_models`), prints a diff, asks, and writes with `backup_and_replace`
(`runtimes/policy_apply.py:510-519`). It works on text, so every other byte stays. It never reads or writes `abk.local.yaml`.

The split of an abk.yaml into a tracked file and an ignored `abk.local.yaml` is the other half of the same chore, and it has no command:

- `docs/configuration.md` says which setting belongs in which file ("Which file holds what", lines 22-40, and "Which file holds a setting", lines 748-791: the table at 755-762
  lists `repos.<name>.path`, `repos.<name>.deploy.ssh_key`, `planning.worktree_root`, a `verify.env` entry holding a home path, `runtimes.<name>.limits`, `project_limits`).
- `abk doctor`'s `machine keys` check (`_machine_keys`, `cli/doctor.py:944-1002`, change `config-files-guidance/1`) already classifies a committed abk.yaml: it **warns** for
  `repos.<name>.account`, `project_limits`, `runtimes.<name>.accounts`, an absolute program path in `runtimes.<name>.command` / `policy_fix` and `tests.e2e_available`, and
  **notes** `runtimes.<name>.limits`, `tests.e2e_schedule` off and a split's `hold`, each ending "move it to abk.local.yaml" (lines 962, 995-1001). It says nothing of the path
  settings of the documentation table. A separate `public content` check (`_committed_facts`, `doctor.py:841-884`) warns on a repo path outside the checkout and on any
  string holding a home path (`_HOME_PATH`, `doctor.py:813`).
- The merge the move relies on is in `config.py`: `merge_local` (`1723-1732`, mappings merge by key, a list, text or `null` replaces whole), `overlay_path` (`1750-1752`),
  `read_base` (`1755-1760`), `read_overlay` (`1763-1765`), `OVERLAY_FILENAME` (`52`). The overlay is ignored by git; `abk init` adds `abk.local.yaml`, `scrub.local` and the
  redaction copies to `.gitignore` (`LOCAL_IGNORES`, `init/scaffold.py:629`, `append_missing_lines`, `pipeline/file_lock.py:78-92`).
- A build or track run fails with `ConfigChanged` when either file differs after it from before it (`pipeline/config_guard.py:20-78`), so a migration that writes either file
  fails the units that are running when it does.

On 2026-10-21 this installation's own abk.yaml was split by hand with a one-off script. The person wants the command to do it, with the safety the other moves already have.

Facts checked while writing this change, where they differ from what was assumed:

- **There is no tick lock.** `cmd_tick` (`cli/pipeline.py:1198-1253`) takes no lock for its length; the file locks in the code guard single files (`file_lock`, `try_file_lock`,
  `pipeline/file_lock.py:25-49`), and `tick.json` (`pipeline/loaded_code.py:20, 103-124`) records a start and is never cleared. A running build is known only from the unit store
  (`UnitStore`, `pipeline/unit_store.py:629-700`, at `<state_dir>/units.json`, `cli/pipeline.py:470-471`): a unit in state `running` (`UnitState.RUNNING`, `pipeline/units.py:36-49`)
  has a worktree open and an agent working. So the command can name running units but cannot refuse on a lock; a unit left `running` by a crashed tick would also make any refusal
  permanent.
- **The doctor's machine-keys check has no main spec.** `config-files-guidance` is not under `openspec/specs` or `openspec/changes/archive` of the planning repo; this change
  describes the check in `public-config-doctor` (an ADDED requirement) rather than modifying one.

## What Changes

- **One table of machine settings.** The classification in `_machine_keys` moves to one module that both `abk doctor` and the migration read. It gains the path settings
  of the documentation table: `repos.<name>.path` (when it resolves outside the planning repository's top level), `repos.<name>.deploy.ssh_key`, `planning.worktree_root`, and,
  inside `verify.env.<NAME>`, the key that holds a home path (`file`, `value` or `argv`). Two classes as in the doctor: a **machine choice** (the warned ones and the paths), moved
  by default, and a **fine-to-commit default** (`runtimes.<name>.limits`, `e2e_schedule: off`, a split's `hold`), moved only with `--include-defaults`.
- **The move.** After the existing migration steps have run on the text, each machine setting of a git-tracked abk.yaml is lifted out, with the comment lines directly above it and
  its own line comments, and placed under the same path in `abk.local.yaml`, creating the file, or its missing parent keys, when absent. Only the moved key moves: the rest of a repo
  entry stays. A parent left with nothing is written `{}`.
- **Safety.** The merged configuration of the two new texts equals the merged configuration of the two old ones, compared in memory before anything is written. A key the local file
  already sets (the path, a key beneath it, or a non-mapping above it) is left in both files and reported. Anything that cannot be edited by lines (an anchor, an alias, flow style,
  a merge key, several documents) is refused, naming the key and the file.
- **Both files, both-or-neither.** Both new texts are written to temporary files and read back before either file is replaced; the local file is replaced first and the tracked one
  second; if the second fails the first is restored from the original held in memory. Each existing file is backed up once, as the command does today.
- **Git hygiene.** Before a local file is written the command makes sure `.gitignore` covers `abk.local.yaml` and `scrub.local` (adding the lines and showing the change, in a git
  repository), refuses when `abk.local.yaml` is tracked, says when `abk.yaml` had uncommitted changes, and never stages or commits anything.
- **A notice about running units.** When the unit store holds units in state `running`, the command says so before it asks, and says to run it between ticks.
- **Doctor, documents, skill, changelog.** The doctor's messages end with the command that makes the move, and `docs/configuration.md`, `docs/cli.md`, the `abk-config` skill source
  and `CHANGELOG.md` say so.

## Impact

A person (or an agent acting for one) with a committed abk.yaml full of paths runs `abk config --migrate`, reads two diffs and one question, and ends with the same merged
configuration split the way the documentation says. The doctor's `machine keys` check now also finds the path settings, so a clean doctor after the migration means the split is done.
A run of `--migrate` over a file the old command would have left alone now may also propose a move to `abk.local.yaml`; it asks first, as before, and `--dry-run` shows it. An
installation whose abk.yaml is not tracked by git sees no change in what the command does.

## Not in this change

- **A refusal on a held tick lock.** None exists (see above). The command notices; it does not refuse. A lock held by the tick, or detection of a live tick process, is a separate change.
- **Moving anything from `abk.local.yaml` to `abk.yaml`**, moving `.env` values, rewriting comments, and any change to which settings count as machine settings beyond the documented table
  (`runtimes.<name>.accounts.<label>.config_dir` is under the accounts block and moves with it; `runtimes.claude_code.usage_cache_*` is not in the doctor's list and does not move).
- **A split of an abk.yaml that git does not track.** Nothing in it can reach a public repository, the doctor says nothing about it, and the command leaves it as it is.
- **`abk init`'s template**, the `public content` check's own findings (a repo path outside the checkout, a home path) and the existing migration steps.
- **A commit.** The command never commits, stages or pushes.
