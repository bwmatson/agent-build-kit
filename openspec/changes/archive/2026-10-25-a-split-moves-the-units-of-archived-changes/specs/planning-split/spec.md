## MODIFIED Requirements

### Requirement: Units move with their change, and a unit that cannot move whole blocks the run

A unit's member changes are its own change and each `joined` change, named by the plain change name. Each SHALL be resolved against the source's change directories and archive entries, an archive entry `YYYY-MM-DD-<change>` by its name without the date. A change name is **moving** when every directory of that name is moved, **staying** when it has directories and none is moved, **ambiguous** when some are moved and some are not, and **absent** when it has no directory. The units moved SHALL be those whose every member change is moving, or absent under the rule for a unit with no change directory. A mixed change that `--allow-mixed destination` moves SHALL bring its archive entries and its units; `--allow-mixed source` SHALL keep them. A unit that builds groups of a moving and of a staying change SHALL be an error naming the unit and both changes. A unit with an ambiguous member SHALL be an error naming the unit and the change. A unit in `running`, `in_review` or `held` SHALL be an error naming the unit and its state, with the advice to settle it and run again, whatever kind of change it belongs to. All of these SHALL be reported together with every other refusal, and nothing SHALL be written.

#### Scenario: Units of moved changes are chosen

- **GIVEN** units of a moved change and of a staying change
- **WHEN** the plan is made
- **THEN** exactly the first change's units are selected

#### Scenario: Units of a moved archive entry are chosen

- **GIVEN** an archive entry `2026-01-05-done` tagged only for the moving repo, merged units whose `change` is `done`, and merged units of an archive entry tagged for another repo
- **WHEN** the plan is made
- **THEN** exactly the units of `done` are selected, though no active change of that name exists

#### Scenario: A unit of a staying archive entry stays

- **GIVEN** merged units of an archive entry tagged for another repo
- **WHEN** the plan is made for the moving repo
- **THEN** they are not selected and are not refused

#### Scenario: A mixed change's archive entries follow the side named

- **GIVEN** an archive entry tagged for the moving repo and another repo, with merged units
- **WHEN** the plan is made with `--allow-mixed destination`, and again with `--allow-mixed source`
- **THEN** the entry and its units are selected the first time and neither is the second

#### Scenario: A spanning unit

- **GIVEN** a unit of a moved change that carries a `joined` member of a staying change
- **WHEN** the plan is made
- **THEN** it is an error naming the unit and both changes, and the exit is 1

#### Scenario: A unit spanning a moved archive entry and a staying change

- **GIVEN** a merged unit of a moved archive entry that carries a `joined` member of a staying active change
- **WHEN** the plan is made
- **THEN** it is the same error, naming the unit and both change names

#### Scenario: A change name whose directories disagree

- **GIVEN** a change name with one archive entry that moves and one active directory that stays
- **WHEN** the plan is made
- **THEN** a unit of that name is an error naming the unit and the change, and is not moved

#### Scenario: A unit in flight

- **GIVEN** a unit of a moved change in `in_review`
- **WHEN** the split is applied
- **THEN** it is an error naming the unit and `in_review`, and nothing is written

#### Scenario: A merged or failed unit moves

- **GIVEN** units of a moved change in `merged` and in `failed`
- **WHEN** the plan is made
- **THEN** both are selected

### Requirement: An edge that would point at nothing is an error naming it

Before any write, for every moved unit each `depends_on`, `needs` and `superseded_by` id SHALL be a moved unit or already be in the destination, and each `joined` member's change SHALL be a moved active change, a moved archive entry (by its name without the date), a change the moved units carry with no directory, or a change already in the destination (active or archived). The one exception is a dependency on a merged unit of another repo that stays, which the requirement "A dependency on a merged unit of another repo is carried as satisfied history" settles. A `Needs: <change> group <n>` line in a moved `tasks.md` SHALL be held to the same rule at the change level. Each failure SHALL be one error line naming the unit or change, the field and the target, all listed together, with exit 1 and nothing written. An edge from a staying unit or change to something moved SHALL be listed as a warning, and as an error under `--remove`, except an edge from a staying unit to a moved unit in state `merged`, which SHALL be a warning under `--remove` as well.

#### Scenario: A dependency on a unit that stays

- **GIVEN** a moved unit whose `depends_on` names a staying unit of the same repo
- **WHEN** the split is applied
- **THEN** the error names the unit, `depends_on` and the target

#### Scenario: A dependency on an archived unit that moves

- **GIVEN** a moved unit whose `depends_on` names a merged unit of a moved archive entry
- **WHEN** the split is applied
- **THEN** it is copied and no error is raised

#### Scenario: A dependency already in the destination is fine

- **GIVEN** a moved unit whose `needs` names a unit already in the destination store
- **WHEN** the split is applied
- **THEN** it is copied and no error is raised

#### Scenario: A joined member of another change

- **GIVEN** a moved unit with a `joined` member of a change that stays and is not in the destination
- **WHEN** the plan is made
- **THEN** the error names the unit, `joined` and the change

#### Scenario: A joined member that is a moved archive entry

- **GIVEN** a moved unit with a `joined` member whose change exists only as a moved archive entry
- **WHEN** the plan is made
- **THEN** no error is raised for that member

#### Scenario: A change-level needs

- **GIVEN** a moved `tasks.md` with `Needs: other group 2` where `other` stays
- **WHEN** the plan is made
- **THEN** the error names the change, the line's group and `other`

#### Scenario: A staying edge into the moved set

- **GIVEN** a staying unit whose `depends_on` names a moved unit that is not merged
- **WHEN** the plan is made without `--remove`
- **THEN** it is a warning, and with `--remove` it is an error

#### Scenario: A staying edge into a moved merged unit

- **GIVEN** a staying unit of another repo whose `depends_on` names a moved merged unit
- **WHEN** the plan is made with `--remove`
- **THEN** it is a warning, and the staying unit's record is not changed

### Requirement: The run is a dry run unless `--apply` is given

Without `--apply` the command SHALL print the plan and write nothing, in either repo. The plan SHALL show the source and destination, the selection, a count for each kind (changes, archive entries, specs, units, plan records, config entries), every refusal as its own line, the uncommitted files read, the scrub counts, and a last line that says nothing was written and how to apply. Under the unit count it SHALL show how the units divide: moved for active changes, moved for archived changes, moved by repo with no change directory (with their ids), and left in the source; and it SHALL list each dependency dropped as satisfied history, one line each, with their count. `units: N` SHALL remain the total moved. The exit SHALL be 0 when nothing is refused, 1 when anything is, and 2 for a usage problem or an installation that does not load. `--dry-run` SHALL be accepted as the default's spelling and be a usage problem with `--apply`. `--remove` without `--apply` SHALL print what it would remove.

#### Scenario: The default writes nothing

- **GIVEN** a source with a moved change
- **WHEN** it is split without `--apply`
- **THEN** the destination and the source are byte for byte as before, and the plan counts the change

#### Scenario: Counts for each kind

- **GIVEN** two changes, one archive entry, one spec, three units and two plan records to move
- **WHEN** the plan is made
- **THEN** it prints each kind with those counts

#### Scenario: Units are counted by where they came from

- **GIVEN** two units of a moved active change, three of a moved archive entry, one with no change directory of the moving repo, and four units that stay
- **WHEN** the plan is made
- **THEN** it prints `units: 6` with `2` for active changes, `3` for archived changes, `1` with no change directory, and `4` left in the source

#### Scenario: A rule applied is named in the output

- **GIVEN** a moved unit with a no-directory change and a moved unit whose dependency on a merged unit of another repo is dropped
- **WHEN** the plan is made
- **THEN** the output names the first unit's id on its no-directory line and prints one line for the dropped dependency naming the unit, the field and the target

#### Scenario: The exit code follows the refusals

- **GIVEN** a plan with a mixed change and no `--allow-mixed`
- **WHEN** it is made
- **THEN** the exit is 1, and with nothing refused it is 0

#### Scenario: The two flags that cannot go together

- **WHEN** `--dry-run --apply` are given
- **THEN** the run exits 2 saying so

#### Scenario: A remove without apply is described

- **WHEN** `--remove` is given without `--apply`
- **THEN** the plan lists what would be removed, the archived units' records among it, and nothing is

### Requirement: `--remove` removes only what was moved, after the copy is verified

With `--apply --remove` the command SHALL copy, then re-read the destination and verify each file's bytes and each record against what was to be written, and only then remove from the source the moved change, archive and spec directories (the files it moved, and a directory only when empty), exactly the unit records that moved (those of active changes, of archive entries and of changes with no directory included, and no other), the moved plan records, and the repo's entry in `abk.yaml`. A mismatch SHALL stop before anything is removed. It SHALL remove no other file: not another change, the usage ledger, spec snapshots, run logs or the other repos' records, and it SHALL not rewrite a record that stays. The repo's entry SHALL be removed only when no remaining unit has that `repo`, no remaining change or archive entry (readable or not) has a group tagged for it, and no other repo lists it in `consumes`; otherwise the entry SHALL be kept, the run SHALL print `kept repo <key>: still named by <list>`, and the exit SHALL be 1 after the rest is done. `--project` SHALL never edit the source's repo entry.

#### Scenario: What was moved is gone from the source

- **GIVEN** a moved change, its units and its plan record
- **WHEN** the split is applied with `--remove`
- **THEN** the change directory, the unit records and the plan record are gone from the source and present in the destination

#### Scenario: Archived units are removed with their entry

- **GIVEN** a moved archive entry and merged units of it, and a merged unit of another repo
- **WHEN** the split is applied with `--remove`
- **THEN** the entry and its units are gone from the source and present in the destination, and the other repo's unit is unchanged

#### Scenario: A unit with no change directory is removed

- **GIVEN** a unit of the moving repo whose change has no directory
- **WHEN** the split is applied with `--remove`
- **THEN** it is in the destination and gone from the source

#### Scenario: A failed verification removes nothing

- **GIVEN** a destination file that does not match after the copy
- **WHEN** the split is applied with `--remove`
- **THEN** the source is byte for byte as before and the run exits 1 naming the file

#### Scenario: A record that differs after the copy removes nothing

- **GIVEN** a moved archived unit whose record in the destination differs after the copy
- **WHEN** the split is applied with `--remove`
- **THEN** the source is byte for byte as before and the run exits 1 naming the unit

#### Scenario: Nothing else is removed

- **GIVEN** a source with a ledger, spec snapshots, a staying change and another repo's units
- **WHEN** the split is applied with `--remove`
- **THEN** they are all unchanged

#### Scenario: The repo entry goes when nothing names it

- **GIVEN** no remaining unit, change or archive entry names the repo, and no other repo consumes it
- **WHEN** the split is applied with `--remove`
- **THEN** the entry is removed from the source `abk.yaml`, every other line is unchanged, and a backup exists

#### Scenario: The repo entry stays when a unit still names it

- **GIVEN** a unit with the repo that the plan did not move
- **WHEN** the split is applied with `--remove`
- **THEN** the entry is kept, the line `kept repo <key>: still named by` lists the unit, and the exit is 1

#### Scenario: The repo entry stays when something still names it

- **GIVEN** a staying mixed change with a group tagged for the repo
- **WHEN** the split is applied with `--allow-mixed source --remove`
- **THEN** the entry is kept, the line `kept repo <key>: still named by` lists the change, and the exit is 1

#### Scenario: A project split leaves the entry

- **WHEN** the split is applied with `--project web --remove`
- **THEN** the source's repo entry is unchanged

### Requirement: The command is documented where an operator looks

The command's entry in the command reference SHALL give its arguments, the dry-run default, the refusals, what `--scrub` and `--remove` do and what stays at the source, which units move (those of active changes and of archive entries, and a unit with no change directory by its repo), the rule for a dependency on a merged unit of another repo, the exit codes and the order to run it in (destination made by `abk init`, units settled, a dry run read, `--apply`, then `--remove`). The runbook for moving a planning repo SHALL say that archive entries and their units of the moving repo move, that the dry run's split of unit counts is what to compare, and what a dropped dependency or a no-directory unit in the output means. The pipeline skill SHALL mention the command for the case of splitting a planning repo. The changelog SHALL record the command and this change.

#### Scenario: The reference names the flags

- **WHEN** the command reference is searched for `abk planning split`
- **THEN** it has an entry naming `--repo`, `--project`, `--to`, `--allow-mixed`, `--scrub`, `--remove`, `--spec`, `--apply` and the exit codes

#### Scenario: The reference says which units move

- **WHEN** the entry is read
- **THEN** it says units of archive entries move, a unit with no change directory moves by its repo, and a merged foreign dependency is dropped with a note

#### Scenario: The runbook says what is moved

- **WHEN** the runbook is read
- **THEN** its archive and copy steps say archive entries and their units of the moving repo move, and it no longer says that archived units stay

#### Scenario: The skill points at it

- **WHEN** the pipeline skill is read
- **THEN** it names the command and says to run the dry run first

## ADDED Requirements

### Requirement: A unit whose change has no directory moves by its repo and is reported

A unit none of whose member changes has a directory, active or in the archive, SHALL move when its `repo` is the moving repo and, with `--project`, its `project` is that project; it SHALL otherwise stay and not be reported. A unit that has such a member and a moving member SHALL move; one with such a member and a staying member is the spanning error. A moved unit of this kind SHALL be listed by id in the plan on its own line, counted under units moved with no change directory, and SHALL not be refused for lacking a directory. It SHALL be subject to the in-flight check and to the dependency checks as any moved unit is. No file and no plan record is copied for it.

#### Scenario: A unit of the moving repo with no directory moves

- **GIVEN** a merged unit of the moving repo whose change is in neither the changes nor the archive
- **WHEN** the plan is made
- **THEN** the unit is selected, the plan lists its id as moved with no change directory, and nothing is refused

#### Scenario: A unit of another repo with no directory stays

- **GIVEN** a merged unit of another repo whose change is in neither the changes nor the archive
- **WHEN** the plan is made for the moving repo
- **THEN** it is not selected and not reported

#### Scenario: A project selects only its own

- **GIVEN** two no-directory units of the moving repo, one in project `web` and one in the root project
- **WHEN** the plan is made with `--project web`
- **THEN** only the first is selected

#### Scenario: It does not hide an unsettled unit

- **GIVEN** a no-directory unit of the moving repo in `held`
- **WHEN** the plan is made
- **THEN** it is an error naming the unit and `held`

#### Scenario: The repo's entry can go

- **GIVEN** the moving repo's only remaining unit is one with no change directory
- **WHEN** the split is applied with `--remove`
- **THEN** the unit is in the destination and gone from the source, and the repo's entry is removed

### Requirement: A dependency on a merged unit of another repo is carried as satisfied history

For a moved unit's `depends_on` (and the `needs` and `merge_needs` ids among them) naming a unit that is not moved and not in the destination, the edge SHALL be dropped from the record as written when that unit belongs to a repo other than the moving one, is in state `merged`, and its merge is loaded by the tick (a merged unit whose merge is not yet loaded is refused like an unmerged one, saying to run a tick and try again). No other field of the record SHALL change. The plan SHALL print one line for each dropped edge naming the unit, the field and the target, and a count. A target that is unmerged, in any other state, a unit of the moving repo that stays, a `superseded_by` target, or a unit that is not in the source at all SHALL be the dangling-edge error. The record the destination holds, the verification under `--remove` and a second run SHALL all use the same dropped-edge record, so a second run finds it equal.

#### Scenario: A merged foreign dependency is dropped with a note

- **GIVEN** a moved unit whose `depends_on` and `needs` name a merged unit of another repo that stays, and one of the moving repo's units that moves
- **WHEN** the split is applied
- **THEN** the destination's record keeps the moving unit in both lists, has neither list naming the foreign unit, differs from the source in no other field, and the output has a line for each of the two dropped edges

#### Scenario: An unmerged foreign dependency still refuses

- **GIVEN** a moved unit whose `depends_on` names a foreign unit in `in_review`
- **WHEN** the split is applied
- **THEN** the error names the unit, `depends_on` and the target, and nothing is written

#### Scenario: A merged foreign unit not yet loaded refuses

- **GIVEN** a foreign unit in `merged` whose merge the running tick has not loaded
- **WHEN** the plan is made
- **THEN** it is an error naming the unit and the target and saying to run a tick

#### Scenario: A foreign dependency already in the destination is kept

- **GIVEN** a foreign unit with the same id already in the destination store
- **WHEN** the split is applied
- **THEN** the edge is kept and not reported

#### Scenario: A staying unit of the moving repo still refuses

- **GIVEN** a moved unit whose `depends_on` names a merged unit of the moving repo that stays
- **WHEN** the plan is made
- **THEN** it is an error naming the unit, `depends_on` and the target

#### Scenario: The moved unit is not ready early or stuck

- **GIVEN** a planned unit moved with a dropped merged foreign dependency
- **WHEN** the destination's scheduler asks what it waits on
- **THEN** it waits on nothing for that edge, as the source's scheduler also read the edge

#### Scenario: A second run changes nothing

- **GIVEN** a split applied with a dropped edge
- **WHEN** it is run again
- **THEN** it prints `nothing to do` and no file of either repo changes
