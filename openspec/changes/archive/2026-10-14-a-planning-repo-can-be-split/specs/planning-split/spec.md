## ADDED Requirements

### Requirement: A change moves when all its groups are tagged for the selected repo

`abk planning split --repo <key> --to <dir>` SHALL read every active change's `tasks.md` as the file is in the working tree and classify the change by its groups'
tags: **moved** when every group's repo is `<key>`, **staying** when none is, **mixed** when some are. With `--project <path>` a group counts only when its tag is
`<key>/<path>`; without it every project of the repo, the root project included, counts. A `tasks.md` that fails to read SHALL be reported as unreadable and left.
`--project` with a path the repo does not declare SHALL be refused naming the declared projects. An archive entry SHALL be classified by its own `tasks.md` the same way, and one with no
`tasks.md` SHALL be reported as unclassified and never moved.

#### Scenario: Only the selected repo's changes are chosen

- **GIVEN** a source with changes `a` (groups tagged `[app]`), `b` (tagged `[lib]`) and `c` (tagged `[app]` and `[lib]`)
- **WHEN** it is split with `--repo app`
- **THEN** `a` is moved, `b` is staying and `c` is mixed

#### Scenario: A project selects only its own groups

- **GIVEN** a repo `app` declaring project `web`, a change with groups tagged `[app/web]` and one with groups tagged `[app]`
- **WHEN** it is split with `--repo app --project web`
- **THEN** the first change is moved and the second is mixed

#### Scenario: An undeclared project is refused

- **GIVEN** the repo `app` declares only `web`
- **WHEN** it is split with `--repo app --project mobile`
- **THEN** the run exits 2 naming `mobile`, the repo and `web`, and writes nothing

#### Scenario: Archive entries follow their change, and one without tasks is left

- **GIVEN** an archive entry whose `tasks.md` tags only `[app]` and one with no `tasks.md`
- **WHEN** the plan is made
- **THEN** the first is moved and the second is listed as unclassified and is not moved

#### Scenario: An unreadable tasks file is left

- **GIVEN** a change whose `tasks.md` has a heading with no repo tag
- **WHEN** the plan is made
- **THEN** it is listed as unreadable with the file and line and is neither moved nor staying

### Requirement: A main spec moves only when every change that touched it moves

The plan SHALL classify each main spec capability by the changes (active and archived) that have a delta directory of that name: **moved** when every one is moved and at
least one exists, **shared** when moved and staying changes both have one, **unowned** when none has. Shared and unowned capabilities SHALL stay and be listed. `--spec <capability>`
(repeatable) SHALL move a named capability regardless, and a name that is no capability of the source SHALL be refused.

#### Scenario: A spec of a moved change moves

- **GIVEN** a capability whose only delta is in a moved change
- **WHEN** the plan is made
- **THEN** the capability is moved

#### Scenario: A shared spec stays

- **GIVEN** a capability with a delta in a moved change and in a staying one
- **WHEN** the plan is made
- **THEN** it is listed as shared and stays

#### Scenario: A named spec moves anyway

- **GIVEN** an unowned capability
- **WHEN** it is split with `--spec <capability>`
- **THEN** the capability is moved, and without the flag it stays

#### Scenario: A name that is not a capability

- **WHEN** `--spec nothing-here` names no capability of the source
- **THEN** the run exits 2 naming it and writes nothing

### Requirement: A mixed change is reported and refused unless a side is named

A mixed change SHALL be listed with each group's repo and project. Without `--allow-mixed` the run SHALL refuse with exit 1 and write nothing. `--allow-mixed source`
SHALL keep every mixed change, with its archive entries, in the source and move the rest. `--allow-mixed destination` SHALL move every mixed change whole, and SHALL be refused
naming the repo when a group of such a change is tagged for a repo the destination does not declare. Any other value SHALL be a usage error.

#### Scenario: Refused without a side

- **GIVEN** one mixed change
- **WHEN** the split is applied without `--allow-mixed`
- **THEN** the run exits 1, lists the change and its groups' repos, and writes nothing

#### Scenario: The source keeps mixed changes

- **GIVEN** a moved change and a mixed one
- **WHEN** the split is applied with `--allow-mixed source`
- **THEN** only the moved change reaches the destination, and the mixed one and its units are untouched

#### Scenario: The destination takes mixed changes whole

- **GIVEN** a mixed change whose other groups are tagged for a repo the destination declares
- **WHEN** the split is applied with `--allow-mixed destination`
- **THEN** the whole change, all its groups, reaches the destination

#### Scenario: The destination lacks a repo the mixed change names

- **GIVEN** a mixed change with a group tagged for a repo the destination does not declare
- **WHEN** it is split with `--allow-mixed destination`
- **THEN** the run exits 1 naming that repo and the change, and writes nothing

#### Scenario: A value that is no side

- **WHEN** `--allow-mixed both` is given
- **THEN** the run exits 2 saying the values are `source` and `destination`

### Requirement: Units move with their change, and a unit that cannot move whole blocks the run

The units moved SHALL be those whose every member change is moved. A unit that builds groups of a moved and of a staying change SHALL be an error naming the unit and both
changes. A unit in `running`, `in_review` or `held` SHALL be an error naming the unit and its state, with the advice to settle it and run again. Both SHALL be reported
together with every other refusal, and nothing SHALL be written.

#### Scenario: Units of moved changes are chosen

- **GIVEN** units of a moved change and of a staying change
- **WHEN** the plan is made
- **THEN** exactly the first change's units are selected

#### Scenario: A spanning unit

- **GIVEN** a unit of a moved change that carries a `joined` member of a staying change
- **WHEN** the plan is made
- **THEN** it is an error naming the unit and both changes, and the exit is 1

#### Scenario: A unit in flight

- **GIVEN** a unit of a moved change in `in_review`
- **WHEN** the split is applied
- **THEN** it is an error naming the unit and `in_review`, and nothing is written

#### Scenario: A merged or failed unit moves

- **GIVEN** units of a moved change in `merged` and in `failed`
- **WHEN** the plan is made
- **THEN** both are selected

### Requirement: The source is read as it is in the working tree, and what was uncommitted is reported

The command SHALL read the source's files from the working tree, whatever git says: modified and untracked files are read, a file deleted in the tree is not there. It SHALL
print the paths under the specs and state directories that git reports as modified, untracked or deleted, with a count, and SHALL say so when the source is not under git.

#### Scenario: An untracked change is moved

- **GIVEN** a change directory that is untracked in the source
- **WHEN** it is split
- **THEN** it is classified and moved as any other

#### Scenario: A file deleted in the tree is not moved

- **GIVEN** a change whose `proposal.md` is deleted in the working tree but still in `HEAD`
- **WHEN** it is split
- **THEN** the destination does not get it

#### Scenario: The uncommitted files are listed

- **GIVEN** one modified file, one untracked file and one deleted file under the specs directory
- **WHEN** the plan is made
- **THEN** it prints `M`, `??` and `D` with each path and a count of 3

#### Scenario: A source outside git

- **GIVEN** a source that is not a git repository
- **WHEN** the plan is made
- **THEN** it says there is no git information and lists no files

### Requirement: Files are copied without overwriting a different file

Each moved change, archive entry and spec directory SHALL be copied file by file into the destination's specs directory at the same relative path, keeping the file mode, and
lock files (`*.lock`) SHALL not be copied. A destination file with the same bytes SHALL be left. A destination file with different bytes SHALL be a conflict listed with its
path, and nothing SHALL be written when there is one.

#### Scenario: A new change is copied

- **GIVEN** a moved change the destination lacks
- **WHEN** the split is applied
- **THEN** every file of it except lock files exists in the destination with the same bytes

#### Scenario: An identical file is left

- **GIVEN** the destination already holds an identical copy
- **WHEN** the split is applied
- **THEN** the plan counts it as unchanged and the file's modification time does not move

#### Scenario: A different file is a conflict

- **GIVEN** the destination holds a different `design.md` at the same path
- **WHEN** the split is applied
- **THEN** the run exits 1 naming the path and writes nothing

### Requirement: Unit records are copied through the destination store, with their plan records

Moved unit records SHALL be added to the destination's store by a new exclusive method of the store that validates each record as a stored unit, keeps every field (state,
history, branch, pull request, feedback, flag, calibration), writes in the store's own format, and skips a record equal to one already there. A record that differs from
one with the same id SHALL be a conflict naming the id. A moved change's plan record SHALL be written to the destination through the plan-record writer with the hash
recomputed over the text as written there, so a change whose text was scrubbed is not planned again; a change with no source record SHALL get none.

#### Scenario: A record keeps its state and history

- **GIVEN** a merged unit with a branch, a pull request and three history entries
- **WHEN** it is copied
- **THEN** the destination's record equals the source's in every field

#### Scenario: The destination store is written in its own format

- **GIVEN** a destination store of `{"units": []}`
- **WHEN** units are copied
- **THEN** the file is indented JSON with the default priority left out, as the store writes it

#### Scenario: A differing record is a conflict

- **GIVEN** the destination holds a unit with the same id and a different state
- **WHEN** the split is applied
- **THEN** the run exits 1 naming the id and writes nothing

#### Scenario: The plan record's hash follows the written text

- **GIVEN** a moved change scrubbed on the way in
- **WHEN** the destination's tick reads its plan record
- **THEN** the recorded hash is that of the scrubbed `tasks.md`, so the change is not planned again

#### Scenario: A readers' check for an absent run log

- **GIVEN** a copied unit whose `run_log` names a file the destination does not have
- **WHEN** `abk status` and `abk report` read it
- **THEN** they print without an error

### Requirement: An edge that would point at nothing is an error naming it

Before any write, for every moved unit each `depends_on` and `needs` id, and each `joined` member's change, SHALL be a moved unit or change, or already be in the destination. A
`Needs: <change> group <n>` line in a moved `tasks.md` SHALL be held to the same rule at the change level. Each failure SHALL be one error line naming the unit or change, the field and
the target, all listed together, with exit 1 and nothing written. An edge from a staying unit or change to something moved SHALL be listed as a warning, and as an error under `--remove`.

#### Scenario: A dependency on a unit that stays

- **GIVEN** a moved unit whose `depends_on` names a staying unit
- **WHEN** the split is applied
- **THEN** the error names the unit, `depends_on` and the target

#### Scenario: A dependency already in the destination is fine

- **GIVEN** a moved unit whose `needs` names a unit already in the destination store
- **WHEN** the split is applied
- **THEN** it is copied and no error is raised

#### Scenario: A joined member of another change

- **GIVEN** a moved unit with a `joined` member of a change that stays and is not in the destination
- **WHEN** the plan is made
- **THEN** the error names the unit, `joined` and the change

#### Scenario: A change-level needs

- **GIVEN** a moved `tasks.md` with `Needs: other group 2` where `other` stays
- **WHEN** the plan is made
- **THEN** the error names the change, the line's group and `other`

#### Scenario: A staying edge into the moved set

- **GIVEN** a staying unit whose `depends_on` names a moved unit
- **WHEN** the plan is made without `--remove`
- **THEN** it is a warning, and with `--remove` it is an error

### Requirement: `--scrub` strips installation names and home paths from moved text, never from identifiers or code

With `--scrub`, the text of every moved file, and the free-text fields of every moved record (`feedback`, `guidance`, `predecessor_note`, `stack_refusal`, the text of `description`
and each history entry's `note`), SHALL be passed through the public-content change's text scrub with the terms derived from the source installation for the moved repo as target.
A record's identifiers (`id`, `change`, `repo`, `branch`, `run_log`, `trace`, `state` and timestamps) SHALL never be changed. No file of a code repo SHALL be read for
scrubbing or written. Without `--scrub` the bytes SHALL be copied unchanged. The plan SHALL print how many files and records would change and how many substitutions.

#### Scenario: A name and a home path are removed

- **GIVEN** a moved `proposal.md` naming another repo of the source and a path under the user's home
- **WHEN** it is split with `--scrub`
- **THEN** the destination's copy holds neither

#### Scenario: A record's free text is scrubbed and its ids are not

- **GIVEN** a unit whose feedback quotes a home path and whose branch contains a term
- **WHEN** it is split with `--scrub`
- **THEN** the feedback is scrubbed and the id, change, repo and branch are unchanged

#### Scenario: Without the flag the text is byte for byte

- **GIVEN** the same inputs
- **WHEN** it is split without `--scrub`
- **THEN** the destination's files and record text equal the source's

#### Scenario: The moved repo may name itself

- **GIVEN** a moved file naming the moved repo
- **WHEN** it is split with `--scrub`
- **THEN** the repo's name is kept

#### Scenario: The counts are printed

- **GIVEN** two files and one record that the scrub would change
- **WHEN** the plan is made with `--scrub`
- **THEN** it prints `scrub: 2 files, 1 records` and the number of substitutions, and writes nothing

### Requirement: The run is a dry run unless `--apply` is given

Without `--apply` the command SHALL print the plan and write nothing, in either repo. The plan SHALL show the source and destination, the selection, a count for each kind
(changes, archive entries, specs, units, plan records, config entries), every refusal as its own line, the uncommitted files read, the scrub counts, and a last line that says
nothing was written and how to apply. The exit SHALL be 0 when nothing is refused, 1 when anything is, and 2 for a usage problem or an installation that does not load.
`--dry-run` SHALL be accepted as the default's spelling and be a usage problem with `--apply`. `--remove` without `--apply` SHALL print what it would remove.

#### Scenario: The default writes nothing

- **GIVEN** a source with a moved change
- **WHEN** it is split without `--apply`
- **THEN** the destination and the source are byte for byte as before, and the plan counts the change

#### Scenario: Counts for each kind

- **GIVEN** two changes, one archive entry, one spec, three units and two plan records to move
- **WHEN** the plan is made
- **THEN** it prints each kind with those counts

#### Scenario: The exit code follows the refusals

- **GIVEN** a plan with a mixed change and no `--allow-mixed`
- **WHEN** it is made
- **THEN** the exit is 1, and with nothing refused it is 0

#### Scenario: The two flags that cannot go together

- **WHEN** `--dry-run --apply` are given
- **THEN** the run exits 2 saying so

#### Scenario: A remove without apply is described

- **WHEN** `--remove` is given without `--apply`
- **THEN** the plan lists what would be removed and nothing is

### Requirement: The destination must already be an installation

`--to <dir>` SHALL name a directory holding an `abk.yaml` that loads, the specs directory's `<redacted>` carrying the rules stamp, and a state directory; otherwise the run SHALL
exit 2 naming what is missing and the command that creates it (`abk init <dir>`), and write nothing. The command SHALL never create an installation, and SHALL refuse a destination that is the source.

#### Scenario: A directory with no abk.yaml

- **GIVEN** an empty directory
- **WHEN** it is the destination
- **THEN** the run exits 2 naming `abk.yaml` and `abk init`, and writes nothing

#### Scenario: A destination without the rules stamp

- **GIVEN** a destination whose specs `<redacted>` has no `# abk-rules` stamp
- **WHEN** it is the destination
- **THEN** the run exits 2 naming the file

#### Scenario: The source is the destination

- **WHEN** `--to` resolves to the source's root
- **THEN** the run exits 2 saying so

### Requirement: The destination's configuration gains the repo's entry by a text splice

When `repos.<key>` is absent from the destination's `abk.yaml` the command SHALL splice the source's block for it into the destination's `repos:` map as text, its comments and
values unchanged and its indentation made the destination's, after the last repo block; when present it SHALL leave it and say so. The plan SHALL list `consumes:` entries of the
block that name a repo the destination does not declare. Before a write the original SHALL be copied once to `<file>.abk-backup`, the write SHALL be atomic and keep the mode,
and the new text SHALL be checked to parse to the old document plus the block and to load; when it does not nothing, not even the backup, SHALL be written.

#### Scenario: The entry is added with its comments

- **GIVEN** a source block for `app` with a comment above a key, and a destination without `app`
- **WHEN** the split is applied
- **THEN** the destination holds the block with the comment, and every other line of the destination's file is unchanged

#### Scenario: An existing entry is left

- **GIVEN** the destination already declares `app`
- **WHEN** the plan is made
- **THEN** it says `already declared` and the file is not written

#### Scenario: A consumed repo the destination lacks is listed

- **GIVEN** the block has `consumes: [lib]` and the destination declares no `lib`
- **WHEN** the plan is made
- **THEN** the plan names `lib`

#### Scenario: The backup is made once

- **GIVEN** a destination file edited by one run and by a later one
- **WHEN** the second runs
- **THEN** `<file>.abk-backup` still holds the file as it was before the first

#### Scenario: A layout the splice cannot follow

- **GIVEN** a source whose repo block is written in flow style
- **WHEN** the split is applied
- **THEN** it is refused naming the file and the key, and no file is written

### Requirement: `--remove` removes only what was moved, after the copy is verified

With `--apply --remove` the command SHALL copy, then re-read the destination and verify each file's bytes and each record against what was to be written, and only then remove from
the source the moved change, archive and spec directories (the files it moved, and a directory only when empty), the moved unit records, the moved plan records, and the repo's
entry in `abk.yaml`. A mismatch SHALL stop before anything is removed. It SHALL remove no other file: not another change, the usage ledger, spec snapshots, run logs or the other
repos' records. The repo's entry SHALL be removed only when no remaining unit has that `repo`, no remaining change or archive entry (readable or not) has a group tagged for it, and no
other repo lists it in `consumes`; otherwise the entry SHALL be kept, the run SHALL print `kept repo <key>: still named by <list>`, and the exit SHALL be 1 after the rest is done. `--project`
SHALL never edit the source's repo entry.

#### Scenario: What was moved is gone from the source

- **GIVEN** a moved change, its units and its plan record
- **WHEN** the split is applied with `--remove`
- **THEN** the change directory, the unit records and the plan record are gone from the source and present in the destination

#### Scenario: A failed verification removes nothing

- **GIVEN** a destination file that does not match after the copy
- **WHEN** the split is applied with `--remove`
- **THEN** the source is byte for byte as before and the run exits 1 naming the file

#### Scenario: Nothing else is removed

- **GIVEN** a source with a ledger, spec snapshots, a staying change and another repo's units
- **WHEN** the split is applied with `--remove`
- **THEN** they are all unchanged

#### Scenario: The repo entry goes when nothing names it

- **GIVEN** no remaining unit, change or archive entry names the repo, and no other repo consumes it
- **WHEN** the split is applied with `--remove`
- **THEN** the entry is removed from the source `abk.yaml`, every other line is unchanged, and a backup exists

#### Scenario: The repo entry stays when something still names it

- **GIVEN** a staying mixed change with a group tagged for the repo
- **WHEN** the split is applied with `--allow-mixed source --remove`
- **THEN** the entry is kept, the line `kept repo <key>: still named by` lists the change, and the exit is 1

#### Scenario: A project split leaves the entry

- **WHEN** the split is applied with `--project web --remove`
- **THEN** the source's repo entry is unchanged

### Requirement: A second run changes nothing, and the source is not written without `--remove`

A run over what an earlier run moved SHALL find every file and record equal and the entry declared, SHALL print counts of zero and `nothing to do`, and SHALL write nothing and exit
0. Without `--remove` the command SHALL not write to the source in any way: no file, no backup, no lock file, no copy of a store. A run killed between the copy and the removal SHALL be completed by the
next.

#### Scenario: Running it twice

- **GIVEN** a split that was applied
- **WHEN** the same command is run again
- **THEN** it prints `nothing to do`, exits 0 and no file of either repo changes

#### Scenario: The source is untouched without remove

- **GIVEN** a split applied without `--remove`
- **WHEN** the source tree is compared with a copy taken before
- **THEN** no file differs, none was added and no modification time moved

#### Scenario: An interrupted remove is finished

- **GIVEN** a destination holding everything and a source that still has the units
- **WHEN** the split is applied with `--remove`
- **THEN** the source's moved content is removed and the destination is unchanged

### Requirement: The command is documented where an operator looks

The command's entry in the command reference SHALL give its arguments, the dry-run default, the refusals, what `--scrub` and `--remove` do and what stays at the source, the exit codes
and the order to run it in (destination made by `abk init`, units settled, a dry run read, `--apply`, then `--remove`). The pipeline skill SHALL mention the command for the case of
splitting a planning repo. The changelog SHALL record the command.

#### Scenario: The reference names the flags

- **WHEN** the command reference is searched for `abk planning split`
- **THEN** it has an entry naming `--repo`, `--project`, `--to`, `--allow-mixed`, `--scrub`, `--remove`, `--spec`, `--apply` and the exit codes

#### Scenario: The skill points at it

- **WHEN** the pipeline skill is read
- **THEN** it names the command and says to run the dry run first
