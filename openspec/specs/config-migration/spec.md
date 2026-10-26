# config-migration Specification

## Purpose
TBD - created by archiving change limits-split-into-global-and-project. Update Purpose after archive.

## Requirements

### Requirement: `abk config --migrate` moves an abk.yaml to the new limits blocks by text

`abk config --migrate` SHALL rewrite the abk.yaml in force so that a root `limits` key becomes `global_limits` and the settings
`max_units_in_progress`, `max_concurrent_stacks` and `max_concurrent_restacks` found under it (or already under `global_limits`)
are moved into a `project_limits` block placed straight after the `global_limits` block, each with its value, the comment at
the end of its line, and the comment lines directly above it. It SHALL write by editing the file's original text, never by writing
the parsed document out again: every other byte of the file (comments, spellings of values, spacing, key order, line breaks,
indentation, document markers, a missing final newline) SHALL be unchanged. When `global_limits` would be left with no setting it
SHALL be written as `global_limits: {}`. The key and the indentation of the moved lines SHALL follow the file's own style.
Before it writes it SHALL check that the new text parses and holds exactly the old document with those keys renamed and moved,
and it SHALL write nothing when that is not so.

#### Scenario: The old block is renamed and the three are moved

- **GIVEN** a file with `limits:` holding `max_review_rounds`, `max_units_in_progress`, `max_concurrent_stacks` and `max_concurrent_restacks`
- **WHEN** it is migrated
- **THEN** `limits:` reads `global_limits:` holding only `max_review_rounds`, and a `project_limits:` block follows it holding the other three with their values and comments

#### Scenario: Every other byte is unchanged

- **GIVEN** a file with comments, quoted values, `~` and `null`, extra spaces before a value or a comment, mixed indentation, CRLF line endings, a leading `---` and no final newline
- **WHEN** it is migrated
- **THEN** the diff of before and after holds only the renamed key line, the removed lines of the three settings and the added `project_limits` lines, and every other line is byte for byte as it was

#### Scenario: A block left empty

- **GIVEN** a `limits` block holding only the three settings
- **WHEN** it is migrated
- **THEN** it reads `global_limits: {}` and the three are under `project_limits`, and the file loads

#### Scenario: A file already on the new names with one left behind

- **GIVEN** a `global_limits` block that still holds `max_units_in_progress`
- **WHEN** it is migrated
- **THEN** only that setting moves to `project_limits`, and `global_limits` keeps its name

#### Scenario: Comments move with their setting

- **GIVEN** a comment line directly above `max_concurrent_stacks` and a comment at the end of its line
- **WHEN** it is migrated
- **THEN** both are in `project_limits` with the setting, and a comment above a setting that stays remains where it was

#### Scenario: The result loads

- **WHEN** a migrated file is loaded
- **THEN** it loads with no deprecation notice and the same limits it meant before

### Requirement: A migration refuses what it cannot edit safely and writes nothing

`abk config --migrate` SHALL refuse, naming the file and the key and saying why, exiting 2 and writing nothing (no backup and no
temporary file), when the file does not parse, has several documents, holds a `limits` and a `global_limits` together, writes the
block in flow style or as a single value, writes a moved setting with a value on more than one line, gives a moved key with an
anchor or a merge key, or already holds the same setting in `project_limits`.

#### Scenario: A block in flow style

- **GIVEN** `limits: {max_units_in_progress: 5}`
- **WHEN** it is migrated
- **THEN** it refuses naming `limits` and says a flow-style block cannot be edited without rewriting the line, and the file is unchanged

#### Scenario: Both old and new keys

- **GIVEN** a file with `limits` and `global_limits`
- **WHEN** it is migrated
- **THEN** it refuses naming both keys, and the file is unchanged

#### Scenario: The setting is already in `project_limits`

- **GIVEN** `project_limits: {max_units_in_progress: 3}` and `limits: {max_units_in_progress: 5}`
- **WHEN** it is migrated
- **THEN** it refuses naming the setting, and the file is unchanged

#### Scenario: A file that does not parse

- **WHEN** the file is not valid YAML
- **THEN** it refuses, naming the file, and writes nothing

### Requirement: A migration keeps one backup, asks, and is idempotent

The first time `abk config --migrate` writes a file it SHALL copy the original to `<file>.abk-backup` beside it and SHALL never
overwrite that copy. It SHALL write through a temporary file in the file's directory, keeping the file's mode, and replace the
file in one step. It SHALL print a diff of the change to each file it would change (abk.yaml, and `abk.local.yaml` and `.gitignore` when the
machine-settings move or the ignore lines change them) and ask once, for all of them, before writing, unless `--yes` is given; `--dry-run` SHALL print the
diffs and write nothing; a person who declines, and a run with no terminal to ask on and no `--yes`, SHALL write nothing and exit 1. It SHALL exit 0
when it wrote and when nothing needed migrating. Run again on a migrated file it SHALL say nothing needed migrating, write
nothing and make no second backup.

#### Scenario: A yes writes

- **WHEN** the person confirms
- **THEN** the diffs are printed first, the files are written, the backups' paths are printed, and the exit status is 0

#### Scenario: `--yes` does not ask

- **WHEN** `abk config --migrate --yes` runs
- **THEN** it prints the diffs, asks nothing and writes

#### Scenario: A no, or no terminal

- **WHEN** the person declines, or the command runs with no terminal and no `--yes`
- **THEN** no file, backup or temporary file is written and the exit status is 1

#### Scenario: A dry run

- **WHEN** `abk config --migrate --dry-run` runs
- **THEN** the diffs are printed, nothing is written (no file, backup, `.gitignore` change or temporary file) and the exit status is 0

#### Scenario: A second run

- **GIVEN** a file that was migrated
- **WHEN** the command runs again
- **THEN** it says nothing needed migrating, asks nothing, writes nothing, makes no second backup and exits 0

#### Scenario: The backup is kept once

- **GIVEN** a backup from an earlier migration of the same path
- **WHEN** a later migration writes
- **THEN** the backup still holds the first original

#### Scenario: A file that does not load for a moved setting

- **GIVEN** a file whose `global_limits` holds a moved setting, so it does not load
- **WHEN** `abk config --migrate` runs
- **THEN** it migrates it, because the command does not load the configuration first, and with `--config` it migrates the named file

#### Scenario: One question for two files

- **GIVEN** a tracked abk.yaml with a root `limits` and a repo path outside the checkout
- **WHEN** the command runs with no `--yes` on a terminal
- **THEN** it prints the diff of abk.yaml and the diff of the new `abk.local.yaml`, asks one question naming both files, and writes both after one yes

### Requirement: `abk config --migrate` moves the machine settings of a tracked abk.yaml to abk.local.yaml

When the abk.yaml in force sits in a git repository and is tracked by it, `abk config --migrate` SHALL, after the other steps it makes have run on the text, move each
**machine choice** found in it to the same key path in `abk.local.yaml`, beside it, by editing the text of both files and changing no other byte. The machine choices are:
`repos.<name>.account`; `repos.<name>.path` when it resolves outside the repository's top-level directory; `repos.<name>.deploy.ssh_key`; `planning.worktree_root`; `project_limits`;
`runtimes.<name>.accounts`; `runtimes.<name>.command` and `runtimes.<name>.policy_fix` when the program is an absolute path; `tests.e2e_available` and
`repos.<name>.tests.e2e_available`; and, inside each `verify.env.<NAME>` entry, the key `file`, `value` or `argv` whose value holds a home-directory path. Only the named key moves:
every other key of a repo, a runtime or a `verify.env` entry stays in abk.yaml. The lines moved are the key's own lines with their end-of-line comments and the comment lines directly
above it; they are re-indented to their depth in the local file and otherwise copied as written. The local file SHALL be created when absent, and a missing parent key SHALL be
written once; a setting goes at the end of its deepest existing parent's block. A parent left with no key SHALL be written `{}`. The merged configuration (the abk.yaml merged with the
local file) of the new texts SHALL equal that of the old ones, compared in memory before anything is written, and SHALL be refused, naming the key, when it does not. The same list is
the one `abk doctor` reads. The command SHALL change nothing about machine settings when abk.yaml is not in a git repository or is not tracked.

#### Scenario: A tracked file with paths, a limit and a home-path variable

- **GIVEN** a git repository tracking an `abk.yaml` with `repos.app` (`slug`, `profile`, `path: ../app` beside a comment, `deploy.ssh_key: ~/.ssh/deploy`), `planning.worktree_root: <home>/work/trees`, a `project_limits` block of two settings and a `verify.env.TOKEN` entry (`from: env-file`, `file: ~/.config/app/.env`, `key: TOKEN`), and no `abk.local.yaml`
- **WHEN** `abk config --migrate --yes` runs
- **THEN** `abk.local.yaml` holds `repos.app.path` (with its comment), `repos.app.deploy.ssh_key`, `planning.worktree_root`, `project_limits` and `verify.env.TOKEN.file`; `abk.yaml` keeps `slug`, `profile`, `from`, `key`, a `deploy: {}`, and `planning: {}`; and the merged configuration read from the two files equals the one read from the old `abk.yaml`

#### Scenario: Only the key that differs moves

- **GIVEN** a tracked `repos.app` holding `slug`, `profile`, `account: work` and `tests`
- **WHEN** the command runs
- **THEN** only `account` goes to the local file, under `repos: app:`, and `slug`, `profile` and `tests` are byte for byte where they were

#### Scenario: A path inside the checkout stays

- **GIVEN** a repo entry with `path: .` and another with `path: ./tools/x` inside the repository
- **WHEN** the command runs
- **THEN** neither path moves

#### Scenario: Comments move with their setting

- **GIVEN** a comment line directly above `planning.worktree_root` and a comment at the end of its line, and a blank line above that comment
- **WHEN** the command runs
- **THEN** both comments are in the local file with the setting, and the blank line and the comments above it stay in abk.yaml

#### Scenario: Existing local blocks are joined by path

- **GIVEN** an `abk.local.yaml` that holds `repos: app: account: personal` and an abk.yaml whose `repos.app.path` is a machine choice
- **WHEN** the command runs
- **THEN** `path` is added under the existing `repos: app:` block with that block's indentation, `account` is unchanged, and the file's other lines are as they were

#### Scenario: Line endings and a missing final newline

- **GIVEN** an abk.yaml with CRLF line endings and no final newline
- **WHEN** the command moves a setting out of it
- **THEN** every other line is byte for byte as it was, the end of the file is as it was, and the new local file's lines use CRLF

#### Scenario: The other steps run first

- **GIVEN** an abk.yaml with a root `limits` holding `max_units_in_progress`
- **WHEN** the command runs
- **THEN** `limits` is renamed `global_limits`, the setting is moved to `project_limits` by the existing step, and that `project_limits` block is then moved to the local file, all in one change shown as one diff of abk.yaml

#### Scenario: Policy stays

- **GIVEN** a `runtimes.claude_code.models` block and a `global_limits` block
- **WHEN** the command runs
- **THEN** neither moves

#### Scenario: An untracked file or no repository

- **GIVEN** an abk.yaml that git does not track, or one in a directory that is not a git repository, holding a repo path outside the directory
- **WHEN** the command runs
- **THEN** nothing about machine settings is proposed, no local file is created, and the output is what it was before this change

#### Scenario: A default stays without the option

- **GIVEN** a tracked `runtimes.claude_code.limits`, a `tests.e2e_schedule: off` and a split `hold`
- **WHEN** the command runs without `--include-defaults`
- **THEN** none of them moves

### Requirement: `--include-defaults` also moves the settings a team may commit

With `--include-defaults`, `abk config --migrate` SHALL move the **fine-to-commit defaults** as well, by the same rules as the machine choices: `runtimes.<name>.limits`,
`tests.e2e_schedule` and `repos.<name>.tests.e2e_schedule` when `off` or `false`, and `tests.e2e_splits.<split>.hold` and the same under a repo's `tests`. Without it these SHALL be left
as they are. `--include-defaults` SHALL need `--migrate`: given without it, the command SHALL say so on the error stream and exit 2.

#### Scenario: The option moves the defaults

- **GIVEN** a tracked `runtimes.claude_code.limits` block, `tests.e2e_schedule: off` and `tests.e2e_splits.slow.hold: true`
- **WHEN** `abk config --migrate --include-defaults --yes` runs
- **THEN** the three are in the local file under their paths, they are gone from abk.yaml except for emptied parents written `{}`, and the merged configuration is unchanged

#### Scenario: The option with no default present

- **GIVEN** a file with no such setting
- **WHEN** the command runs with the option
- **THEN** the result is the same as without it

#### Scenario: The option needs `--migrate`

- **WHEN** `abk config --include-defaults` runs
- **THEN** it says the option needs `--migrate`, exits 2 and writes nothing

### Requirement: A setting the local file already sets is reported and left

A machine setting SHALL NOT be moved, and SHALL stay in abk.yaml with the local file untouched for it, when `abk.local.yaml` already sets its path, sets any key beneath it, or sets an
ancestor of it to something that is not a mapping. For each one the command SHALL print on standard output a line `left <path> in abk.yaml: abk.local.yaml already sets <path>; keep one of
them`, naming the local path that is set. Equal values count as set. Settings that are not in conflict SHALL still move in the same run. A local key that is only a sibling (another key of
the same entry) SHALL NOT be a conflict.

#### Scenario: The local file already sets the path

- **GIVEN** an abk.yaml with `repos.app.path: ../app` and a `project_limits` block, and an `abk.local.yaml` with `repos.app.path: <home>/code/app`
- **WHEN** the command runs and the change is confirmed
- **THEN** `project_limits` moves; `repos.app.path` stays in abk.yaml and the local file keeps `<home>/code/app`, and the output says `left repos.app.path in abk.yaml: abk.local.yaml already sets repos.app.path; keep one of them`

#### Scenario: Equal values

- **GIVEN** the same value of `planning.worktree_root` in both files
- **WHEN** the command runs
- **THEN** it is reported and left in both files

#### Scenario: The local file sets a key beneath a block

- **GIVEN** a tracked `runtimes.claude_code.accounts` block and a local `runtimes.claude_code.accounts.work.config_dir`
- **WHEN** the command runs
- **THEN** the block is not moved and the output names `runtimes.claude_code.accounts`

#### Scenario: An ancestor set to null

- **GIVEN** a local `repos: {app: null}` and a tracked `repos.app.path` outside the checkout
- **WHEN** the command runs
- **THEN** `path` is reported and left, and the local file is unchanged

#### Scenario: A sibling is not a conflict

- **GIVEN** a local `repos.app.account` and a tracked `repos.app.path` to move
- **WHEN** the command runs
- **THEN** `path` moves beside `account`

#### Scenario: Only conflicts remain

- **GIVEN** a file whose only machine settings conflict with the local file
- **WHEN** the command runs
- **THEN** it prints the reports and `nothing needed migrating`, asks nothing, writes nothing and exits 0

### Requirement: A machine move refuses what it cannot edit by lines and writes nothing

When a machine setting cannot be moved by editing lines, `abk config --migrate` SHALL refuse, naming the file and the key and saying why, exit 2 and write nothing (no backup, no temporary
file, no `.gitignore` change). It SHALL refuse when: the key's line or the line of an ancestor key carries an anchor or an alias; an ancestor mapping, or the key's value spanning lines, is in
flow style; an ancestor mapping uses a merge key, or the setting is present in the parsed document but not written at its path (it came in by a merge key or an alias); the file has several
documents; the same holds of the local file at the place the setting must go; the local file does not parse, has several documents or is not a mapping; or the move would not leave the merged
configuration equal. A flow-style value written wholly on the key's own line SHALL be moved as written. It SHALL be read from the local file only when something would move.

#### Scenario: An anchor on a repo entry

- **GIVEN** a tracked `repos.app: &app` holding a `path` outside the checkout
- **WHEN** the command runs
- **THEN** it refuses naming `repos.app.path` and abk.yaml, says an anchor cannot be edited by lines, and writes nothing

#### Scenario: A flow-style parent

- **GIVEN** `repos: {app: {path: ../app}}`
- **WHEN** the command runs
- **THEN** it refuses naming `repos.app.path` and says a flow-style block cannot be edited without rewriting the line

#### Scenario: A setting that comes from a merge key

- **GIVEN** a repo entry that gets its `path` from a `<<: *defaults` merge key
- **WHEN** the command runs
- **THEN** it refuses naming `repos.app.path` and says the key comes from a merge key or an alias

#### Scenario: A flow-style value on one line

- **GIVEN** `runtimes.claude_code.command: [/opt/claude/bin/claude, -p]` on one line
- **WHEN** the command runs
- **THEN** the line moves as written and the merged configuration is unchanged

#### Scenario: A flow-style place in the local file

- **GIVEN** an `abk.local.yaml` holding `repos: {app: {account: x}}` and a tracked `repos.app.path` to move
- **WHEN** the command runs
- **THEN** it refuses naming `repos.app.path` and `abk.local.yaml`, and writes nothing

#### Scenario: A local file that does not parse

- **GIVEN** an `abk.local.yaml` that is not valid YAML and a tracked machine setting
- **WHEN** the command runs
- **THEN** it refuses naming `abk.local.yaml` and writes nothing, and with no machine setting in abk.yaml the local file is not read

### Requirement: Both files are written together, the local one first

`abk config --migrate` SHALL write `abk.yaml` and `abk.local.yaml` both-or-neither. Before it replaces either it SHALL have both new texts in memory and verified, SHALL have made the backups
(each file's `.abk-backup`, once and never overwritten, the local one only when that file existed), and SHALL have written each new text to a temporary file in the file's own directory with the
file's mode and read it back. It SHALL then replace `abk.local.yaml` first and `abk.yaml` second. When the second replacement fails it SHALL restore the first from the original text held in
memory (deleting the local file when this run created it), remove its temporaries, name the file that failed and exit 2. A failure at any earlier step SHALL leave both files as they were and no
temporary file behind. A state left by a kill between the two replacements, or by a failed restore, holds the setting in both files, which leaves the merged configuration unchanged.

#### Scenario: Both written, both backed up

- **GIVEN** an existing `abk.local.yaml` and a tracked abk.yaml with a machine setting
- **WHEN** the change is confirmed
- **THEN** `abk.yaml.abk-backup` and `abk.local.yaml.abk-backup` hold the original texts, both files hold the new ones, no temporary file remains and the paths of the backups are printed

#### Scenario: A created local file has no backup

- **GIVEN** no `abk.local.yaml`
- **WHEN** the command writes
- **THEN** there is an `abk.yaml.abk-backup` and no `abk.local.yaml.abk-backup`

#### Scenario: The second replacement fails

- **GIVEN** a write of `abk.yaml` that fails after the local file was replaced (the replacement is made to raise)
- **WHEN** the command runs
- **THEN** `abk.local.yaml` is as it was (or deleted if it was new), `abk.yaml` is as it was, no temporary file remains, the output names `abk.yaml` and the exit status is 2

#### Scenario: The first replacement fails

- **GIVEN** a failure when writing the local file's temporary file
- **WHEN** the command runs
- **THEN** neither file changed, no temporary file remains and the exit status is 2 (a backup already made stays, as backups are kept)

#### Scenario: The backup is kept once

- **GIVEN** a backup from an earlier migration of the same path
- **WHEN** a later migration writes
- **THEN** the backup still holds the first original and no second backup is made

#### Scenario: A crash between the two replacements keeps the merged configuration

- **GIVEN** a run stopped after the local replacement and before the tracked one
- **WHEN** the two files are loaded and merged
- **THEN** the merged configuration equals the one before the run, and a new run reports the settings as left because the local file already sets them

### Requirement: The migration makes sure git ignores the local files and never commits

When the planning directory is in a git repository and the migration will write `abk.local.yaml`, it SHALL check, with `git check-ignore`, that `abk.local.yaml` and `scrub.local` are ignored, and
SHALL append each line that is missing to the `.gitignore` beside abk.yaml (creating it when absent) before it writes anything else, and show that change as a diff in the same output as the
others. It SHALL refuse, exit 2 and write nothing when `abk.local.yaml` is tracked by git, naming `git rm --cached abk.local.yaml`. It SHALL say, before it asks, when abk.yaml has changes that git
has not committed, and once more after it writes. It SHALL NOT commit, stage, stash or push, and SHALL leave the index and the head as they were.

#### Scenario: The lines are added

- **GIVEN** a repository whose `.gitignore` lacks both names
- **WHEN** the change is confirmed
- **THEN** `.gitignore` gains `abk.local.yaml` and `scrub.local` once each, the diff of it was shown, and the files are written after it

#### Scenario: Already ignored

- **GIVEN** a `.gitignore` that already covers both, by any rule
- **WHEN** the command runs
- **THEN** `.gitignore` is not changed and no diff of it is shown

#### Scenario: A tracked local file

- **GIVEN** an `abk.local.yaml` that was committed
- **WHEN** the command runs
- **THEN** it refuses naming the file and `git rm --cached abk.local.yaml`, and writes nothing

#### Scenario: Uncommitted changes in abk.yaml

- **GIVEN** an abk.yaml with a change that git has not committed
- **WHEN** the command runs
- **THEN** before the question it says abk.yaml has changes git has not committed and that the migration does not commit, and it says so again after it writes

#### Scenario: No commit is ever made

- **GIVEN** a repository with a head commit and an empty index
- **WHEN** the command writes
- **THEN** `git rev-parse HEAD` is unchanged, `git diff --cached` is empty, and `git status --porcelain` shows abk.yaml as modified and not staged

#### Scenario: No repository

- **GIVEN** a directory that is not a git repository
- **WHEN** the command runs
- **THEN** no `.gitignore` is created or changed (and, as abk.yaml is not tracked, no machine setting moves)

### Requirement: The migration names the running units before it asks

When it would write, `abk config --migrate` SHALL read the unit store (`<planning.state_dir>/units.json` under abk.yaml's directory, the state directory taken from the merged raw documents, default
`runs`) without loading the configuration, and when it holds units in state `running` SHALL print on the error stream, before the question, exactly one of these lines (at most five ids,
then `and <k> more` inside the parentheses): for one unit `abk: 1 unit is running (<id>). A write to abk.yaml or abk.local.yaml fails a build or track run in progress, so run this between ticks or
when it has finished.`; for several `abk: <n> units are running (<id>, <id>). A write to abk.yaml or abk.local.yaml fails a build or track run in progress, so run this between ticks or when they have
finished.` It SHALL NOT refuse, with or without `--yes`: no lock records a tick, and a unit left `running` by a crashed tick would make a refusal permanent. It SHALL print nothing of the kind with
`--dry-run`, when nothing is to change, or when the store is missing, unreadable or holds no running unit, and a failure to read the store SHALL NOT fail the command.

#### Scenario: One running unit

- **GIVEN** a unit store with one unit in state `running`, `a-change/2`
- **WHEN** the command runs and is confirmed
- **THEN** the error stream holds `abk: 1 unit is running (a-change/2). A write to abk.yaml or abk.local.yaml fails a build or track run in progress, so run this between ticks or when it has finished.` before the question, and the files are written after the yes

#### Scenario: Several running units

- **GIVEN** three running units
- **WHEN** the command runs
- **THEN** the line reads `abk: 3 units are running (<id>, <id>, <id>). A write to abk.yaml or abk.local.yaml fails a build or track run in progress, so run this between ticks or when they have finished.`

#### Scenario: Many running units

- **GIVEN** seven running units
- **WHEN** the command runs
- **THEN** the line names five ids and `and 2 more`

#### Scenario: `--yes` still writes and still says it

- **GIVEN** a running unit
- **WHEN** `abk config --migrate --yes` runs
- **THEN** the notice is printed and the files are written; the exit status is 0

#### Scenario: Units that are not running

- **GIVEN** units in state `in_review`, `failed`, `held` and `planned` only
- **WHEN** the command runs
- **THEN** no notice is printed

#### Scenario: A dry run

- **GIVEN** a running unit
- **WHEN** `abk config --migrate --dry-run` runs
- **THEN** the diffs are printed, no running-units notice is printed and nothing is written

#### Scenario: No store

- **GIVEN** no `units.json`, or a corrupt one
- **WHEN** the command runs
- **THEN** no notice is printed and the command goes on as usual

### Requirement: A second run of the whole migration changes nothing

Run over the result of an earlier run, `abk config --migrate` (with or without `--include-defaults`, for the settings that option covers) SHALL find nothing to move, print any reports of settings left
because the local file sets them, print `<abk.yaml>: nothing needed migrating`, ask nothing, write nothing, make no backup, no `.gitignore` change and no temporary file, and exit 0.

#### Scenario: A second run

- **GIVEN** the files left by a confirmed run
- **WHEN** the command runs again
- **THEN** it says nothing needed migrating, the bytes of every file are those of the first run's result, no new backup or temporary file exists and the exit status is 0

#### Scenario: A second run with a default

- **GIVEN** the files left by a run with `--include-defaults`
- **WHEN** the command runs again with it
- **THEN** it changes nothing
