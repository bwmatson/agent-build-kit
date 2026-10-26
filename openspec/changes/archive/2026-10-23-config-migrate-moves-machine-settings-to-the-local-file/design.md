## Context

Code at agent-build-kit `origin/main` (74a22e4a). The proposal lists what the command, the doctor, the loader and the config guard do today and the two facts that differ from the
brief (no tick lock exists; the doctor's machine-keys check has no main spec).

Today's flow in `cmd_migrate` (`cli/config_cmd.py:30-73`): locate the file (`locate`), read it, `migrate(before, runtime_for(path))`, print one diff, stop on `--dry-run`, ask
(`confirmed`, `sys.stdin.isatty()` unless `--yes`), `backup_and_replace`. The migration helpers work on a composed YAML tree for positions and on lines for edits
(`yaml_lines.split_lines`, `node_end`, `insert_lines`, `strip_comment`, `yaml_lines.py:21-70`), refuse what lines cannot edit (`_opened`, `config_migrate.py:169-179`; `_MARKED`, `:43`),
carry comment lines above a key (`_region`, `:68-74`), write `{}` for a block left empty (`_renamed`, `:427-438`) and compare the new document with the old one in memory before
returning (`_verify`, `:441-448`). The new move reuses those helpers and their refusals.

## Decisions

### 1. One table of machine settings

The classification moves out of `_machine_keys` (`doctor.py:953-1002`) into one module that returns, for a parsed abk.yaml document and the planning repository's top-level
directory, a list of settings, each with its key path (a tuple of keys), a short reason, and a class: **machine choice** or **fine-to-commit default**. `_machine_keys` becomes a
reader of that list; the migration is another. No second copy of a key name exists. The table is computed from the parsed document (safe-loaded, so a value that comes from a merge
key or an alias is seen too), and the migration then finds each setting's written position in the composed tree (decision 3).

**Machine choice (moved by default).** The existing warned ones, plus the documented paths:

| Path | Moves when |
|---|---|
| `repos.<name>.account` | set (not null) |
| `repos.<name>.path` | set, and `(abk.yaml's directory / path).expanduser().resolve()` is not inside the git top level (the rule of the `public content` check, `doctor.py:850-861`; `.` and a path inside the checkout stay) |
| `repos.<name>.deploy.ssh_key` | set |
| `planning.worktree_root` | set |
| `project_limits` | non-empty (the whole block moves as one key) |
| `runtimes.<name>.accounts` | non-empty (the whole block, so every `config_dir` goes with it) |
| `runtimes.<name>.command`, `runtimes.<name>.policy_fix` | a list whose first item is an absolute path |
| `tests.e2e_available`, `repos.<name>.tests.e2e_available` | non-empty |
| `verify.env.<NAME>.file`, `.value` or `.argv` | the value holds a home path: the `public content` check's test (`~`, `/home/<x>`, the user's home directory; `_HOME_PATH`, `doctor.py:813`, and the under-home pattern, `doctor.py:846`), moved once to a shared helper that both read. For a list (`argv`) any item holding one. |

A `verify.env` entry is split by key, as the documentation says ("the entry and its `path` stay in `abk.yaml`", configuration.md:33; table at 755-758): `from`, `path`, `key`,
`take` and `strip_prefix` stay, and only the key whose value holds a home path moves. A fresh clone therefore has an incomplete provider until its owner writes the local file,
exactly as it has no repo path (configuration.md:782-786).

**Fine-to-commit default (moved only with `--include-defaults`).** `runtimes.<name>.limits`, `tests.e2e_schedule` and `repos.<name>.tests.e2e_schedule` when `off` or `false`
(the doctor's test, `doctor.py:987`), and `<scope>.e2e_splits.<split>.hold` when set.

**Moves with an option: `--include-defaults`.** Without it these are not touched and the doctor still notes them. The option needs `--migrate`, like `--yes` and `--dry-run`
(`cmd_config`, `config_cmd.py:79-81`).

**Not in the table**, as before: `runtimes.<name>.models`, `global_limits`, and anything else the documentation keeps in `abk.yaml`.

### 2. When the move applies: a git-tracked abk.yaml

The doctor's check returns nothing unless the planning root is a git repository and abk.yaml is tracked (`doctor.py:957-960`). The move uses the same condition, for the same reason:
the point of the split is that a tracked file reads the same on every machine. An abk.yaml outside a git repository, or one git does not track, is left as the existing steps leave it, and
the command says nothing about machine settings. This also keeps a person who runs `--migrate` for the `limits` rename on a private, untracked file from having it split unasked.

### 3. The move, by lines

Runs last, on the text the existing steps produced (`migrate(...)`, `config_migrate.py:144-152`, order unchanged), so a key those steps renamed or relocated is moved at its new path:
`project_limits` is moved from where `_move_limits` placed it; `runtimes.<runtime>.models` is policy and stays.

For each setting of the table, in the order of the file:

1. Find its key node by walking the composed tree along the path (`_pair`, `_block_node`, `config_migrate.py:61, 451`). A setting the parsed document has but no written pair holds
   (it came in by a merge key or an alias) is refused, naming the key.
2. Refuse, naming the key and `abk.yaml`, when the key's line or any ancestor key's line carries an anchor or alias (`_MARKED`), when an ancestor or the key's own value is
   flow-style and spans lines, when an ancestor mapping uses a merge key (`_opened`), or when the file has several documents. A flow-style value that is written on the key's own line
   (`command: [/opt/x/bin, -p]`) is a single line and is moved as written; a flow-style *ancestor* (`repos: {app: {path: <home>/app}}`) is refused.
3. The region moved is the comment lines directly above the key, back to the parent's line or a blank line (`_region`, `:68-74`), through the last line of the key's node
   (`node_end`, `yaml_lines.py:43-60`). Comment lines after the node and blank lines are not part of it. The lines are re-indented to the depth they have in the local file
   (the same step as the tracked file's own: the difference between the key's column and its parent's, else 2) and carry their own line ending.
4. A parent mapping left with no key is written `{}` on its line, keeping its end-of-line comment (the precedent of `global_limits: {}`, `_renamed`, `:427-438`). Only the immediate
   parent is rewritten; `repos` itself keeps its keys.

Placement in the local text: if the file is absent or holds no content line, the lines are written (the file is created, with the line endings of abk.yaml and its mode). If it holds
a block mapping, each missing ancestor key is written once, and the setting goes at the end of its deepest existing ancestor's block (`node_end(...) + 1`, `insert_lines`), with that
block's own indentation; settings of one entry that move together are written under one set of ancestor keys. Moved lines are copied verbatim: a relative path in abk.yaml is
relative to the abk.yaml directory, and `abk.local.yaml` sits in the same directory, so a relative path means the same thing in both.

The local file is refused, naming the key and `abk.local.yaml`, when it does not parse, holds several documents or is not a mapping, or when the place a setting must go is flow-style,
has an anchor or alias on its key's line, or uses a merge key. It is read only when something would move.

**Verification before anything is written.** Let `old_base`, `old_local` be the safe-loaded old texts and `new_base`, `new_local` the new ones. The move is refused, naming the first
differing key, unless all hold: `merge_local(new_base, new_local) == merge_local(old_base, old_local)` (the merged configuration; `config.py:1723-1732`); `new_base` is `old_base`
(after the existing steps) with exactly the moved paths removed and emptied parents `{}`; `new_local` is `old_local` with exactly those paths added with their values. The existing
steps keep their own check (`_verify`, `:441-448`).

### 4. An existing local setting is reported, not overwritten

A setting is **in conflict** when the local file sets its path, sets a key beneath it (for a block that moves whole), or sets an ancestor of it to something that is not a mapping
(a scalar, a list, `null`: the overlay would replace the whole parent). A conflicting setting is not moved: it stays in abk.yaml, the local file is not touched for it, and the command
prints one line per conflict to standard output: `left <path> in abk.yaml: abk.local.yaml already sets <path-or-ancestor>; keep one of them`. The rest of the settings still move.
Equal values are still a conflict: the command does not decide which copy is the intended one. A setting set locally only at a sibling (`repos.app.account` local, `repos.app.path` moved)
is not a conflict; the two merge by key.

### 5. Writing both files: both-or-neither, the local one first

Order of effects, each step started only if the one before succeeded:

0. Everything in memory: the new tracked text, the new local text, the `.gitignore` lines, and the verification of decision 3. Nothing has been touched.
1. `.gitignore` (decision 6), if lines are missing. It comes first because a local file holding machine paths must never exist unignored. Its lines are left if a later step fails: they
   are what `abk init` writes and harm nothing.
2. Backups, each once and never overwritten, as `backup_and_replace` does (`policy_apply.py:510-519`): `abk.yaml.abk-backup`, and `abk.local.yaml.abk-backup` when the local file
   existed. A failure to back up aborts with nothing else written.
3. Both new texts are written to temporary files in their own directories, keeping the mode of the file they replace (`_replace`, `policy_apply.py:522-533`), and each is read back
   and compared with the text in memory. The local temp is also parsed and its merge with the tracked temp is compared once more with the old merged configuration. A failure removes
   both temporaries and writes nothing else.
4. The local temporary is renamed over `abk.local.yaml` (or into place when it is new), then the tracked temporary over `abk.yaml`.
5. If the second rename fails, the first is undone from the original bytes held in memory (the local file restored, or deleted when this run created it), the temporaries are
   removed, and the command exits 2 naming the file that failed. The backup files are not the source of the restore: they hold the first original ever, which can predate this run.

The **local file goes first** on purpose. A crash or a failure between the two renames, or a failure of the undo itself, leaves the key in both files with the same value; the merged
configuration is then unchanged (the local copy wins and is equal), so the installation still works and a second run finds a conflict (decision 4) and reports it. The other order
would leave a key in neither file. A failure leaves no temporary file behind; a kill between the two renames leaves the duplicate and, at most, temporaries.

### 6. `.gitignore`, git, and no commit

Applies when the planning root is a git repository and something will be written to the local file.

- **Ignore lines.** The command checks `git check-ignore -q` for `abk.local.yaml` and for `scrub.local` (`doctor._is_ignored`, `doctor.py:837-838`, moved with the other git helpers
  to where both can read it). Each one not ignored is appended to the `.gitignore` in abk.yaml's directory with `append_missing_lines` (`file_lock.py:78-92`: stripped-line compare,
  one newline, created when missing). The change is shown as a diff with the other two, and is part of the one question.
- **A tracked `abk.local.yaml`** is refused (exit 2, nothing written) with `git rm --cached abk.local.yaml` as the fix: moving machine paths into a tracked file would commit them.
- **Uncommitted changes in abk.yaml** (`git status --porcelain -- abk.yaml` non-empty) are said before the question: `abk.yaml has changes git has not committed; this migration
  does not commit, so review `git diff abk.yaml` and commit it yourself`. After a write the same hint is printed once.
- **Never a commit, `git add`, stash or push.** A test reads `git log -1` and `git status --porcelain` before and after: the head is unchanged, nothing is staged.

### 7. The running-units notice

The command does not load the configuration (an unloadable file must still migrate, `test_config_migrate_unloadable`), so it finds the unit store by reading the two files raw: the
state directory is `planning.state_dir` of the merged raw documents, default `runs`, relative to abk.yaml's directory (absolute and `~` allowed), and the store is
`<state_dir>/units.json` (`cli/pipeline.py:470-471`, `Installation.state_dir`, `installation.py:88-89`). It is read with `UnitStore(path).all()` (`unit_store.py:699-700`, no lock
taken, as every reader does). A missing, unreadable or corrupt store means no notice and no failure.

The units named are those in state `running` (`pipeline/units.py:36-49`): a worktree is open and an agent is working, which is what `ConfigChanged` fails
(`config_guard.py:50-78`). `in_review`, `failed`, `held` and `planned` units run nothing. When it would write (not with `--dry-run`, not when nothing is to change), and there is at
least one, it prints to standard error, before the question, exactly:

- one unit: `abk: 1 unit is running (<id>). A write to abk.yaml or abk.local.yaml fails a build or track run in progress, so run this between ticks or when it has finished.`
- several: `abk: <n> units are running (<id>, <id>, ...). A write to abk.yaml or abk.local.yaml fails a build or track run in progress, so run this between ticks or when they have finished.`

at most five ids, then `and <k> more` inside the parentheses. It is **never a refusal**: no tick lock exists to read, and a unit left `running` by a crashed tick would make a refusal
permanent. `--yes` does not hide the notice and does not need to be given for the command to go on. The question is unchanged.

### 8. Second run, dry run, output and exit codes

- **Second run.** Run over its own result nothing is left to move except conflicts. With no change to either text it prints each conflict line and `<abk.yaml>: nothing needed
  migrating`, asks nothing, writes nothing, makes no backup, no `.gitignore` edit and no temporary file, and exits 0.
- **`--dry-run`** prints the conflict lines, the diffs and the notices that would apply to the files (git hints, but not the running-units notice), writes nothing (no backup, no
  `.gitignore` change, no temporary file) and exits 0.
- **Diffs.** One unified diff per file that changes, in the order `.gitignore`, `abk.yaml`, `abk.local.yaml` (from an empty file, labelled `(new file)`, when created), then one question:
  `migrate <abk.yaml> and <abk.local.yaml>? [y/N] ` (only the files that change are named). Declining, or no terminal and no `--yes`, writes nothing and exits 1.
- **Exit codes** are as today: 0 written, dry run or nothing to do; 1 not confirmed; 2 refused or a write failed.
- The existing steps (`limits`, `max_unit_lines`, test-kind keys, `models`) and the machine move are **one** change, one diff of the tracked file and one question.

### 9. The doctor

`_machine_keys` reads the table and reports as before (a warning for a machine choice, a note for a default), with the path settings added, and the fix text names the command:
`move it to abk.local.yaml with `abk config --migrate``; for a default `fine to commit; move it to abk.local.yaml to differ (`abk config --migrate --include-defaults` moves it)`.
The `public content` check keeps its own findings (a repo path outside the checkout, a home path in a string), so one key can be named by both checks; each has its own message.

### 10. Documents

`docs/configuration.md`: both "Which file holds ..." tables (lines 22-40 and 755-762) and the paragraph under the doctor table (69-75) point to `abk config --migrate` and say what it
moves by default and with `--include-defaults`. `docs/cli.md` (886-900): the synopsis gains `[--include-defaults]` and the section describes the move, the two files, the conflict
report, the notice and the exit codes. The `abk-config` skill source (`skills/abk-config/SKILL.md:149, 353-360`) names the command. One changelog bullet under `## Unreleased`.

## Rejected

- **A refusal when a tick is running.** There is nothing to read (see Context in the proposal). A new lock would be a change to the tick, not to this command.
- **Tracked first, then local (the order the brief suggested).** A failure between the two leaves the key in neither file. Local first leaves it in both, which merges to the same
  configuration.
- **Moving whole `verify.env` entries.** The documentation keeps the entry and its `path` in abk.yaml and moves the one key that differs; whole entries would also move the parts that
  are the same on every machine.
- **Overwriting or merging into an existing local key.** The person decides which copy is right; the command only reports.
- **Dumping the document.** As for every other move, the files are edited by lines so every other byte stays.

## Risks

- A fresh clone of a split file has an incomplete `verify.env` entry (no `file`) and no repo path until the owner writes the local file. That is the documented state
  (configuration.md:782-786) and is why the command asks.
- A comment on a line of its own between two settings that belongs to neither moves with the setting below it; the rule is the one the limits move has always had (`_region`).
- `abk doctor` names a repo path that leaves the checkout twice (`public content` and `machine keys`) until the move is made; after it, neither fires.
- A person running the command while a tick is mid-run gets a notice, not a refusal, and the running unit fails with `ConfigChanged`. The notice is the whole mitigation.
