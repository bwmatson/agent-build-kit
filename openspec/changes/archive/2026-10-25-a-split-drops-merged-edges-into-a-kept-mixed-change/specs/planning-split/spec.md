## MODIFIED Requirements

### Requirement: A dependency on a merged unit of another repo is carried as satisfied history

For a moved unit's `depends_on` (and the `needs` and `merge_needs` ids among them) naming a unit that is not moved and not in the destination, the edge SHALL be dropped from the record as written when that unit is in state `merged`, its merge is loaded by the tick (a merged unit whose merge is not yet loaded is refused like an unmerged one, saying to run a tick and try again), and it stays in the source for one of these reasons: it belongs to a repo other than the moving one; with `--project`, it belongs to another project of the moving repo; or it builds a mixed change that `--allow-mixed source` keeps in the source. No other field of the record SHALL change. The plan SHALL print one line for each dropped edge naming the unit, the field, the target and which of the three reasons applies (`merged unit of another repo`, `merged unit of another project`, `merged unit of a change kept in the source`, each followed by `, stays in the source`), and a `dropped edges: N` count that, when more than one reason occurred, is followed by the count for each. A target that is unmerged or in any other state, a unit that stays for any other reason (its change cannot be read, it is an unclassified archive entry, or it blocks the run), a `superseded_by` target, or a unit that is not in the source at all SHALL be the dangling-edge error. The record the destination holds, the verification under `--remove` and a second run SHALL all use the same dropped-edge record, so a second run finds it equal.

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

#### Scenario: A merged unit of a kept mixed change is dropped with its reason

- **GIVEN** a mixed change `m` with groups for the moving repo and another repo, kept with `--allow-mixed source`, and a merged unit `m/4` of the moving repo; and a moved unit `g/1` of another change whose `depends_on` and `needs` name `m/4`
- **WHEN** the split is applied
- **THEN** `g/1` is written without `m/4` in either list and unchanged in every other field, `m/4` and all of `m`'s units stay in the source, and the output has a line for each of the two dropped edges saying `merged unit of a change kept in the source`

#### Scenario: A merged unit of another project is dropped with its reason

- **GIVEN** a split with `--project`, and a moved unit whose `depends_on` names a merged unit of another project of the same repo
- **WHEN** the split is applied
- **THEN** the edge is dropped and the line says `merged unit of another project`

#### Scenario: An unmerged unit of a kept mixed change still refuses

- **GIVEN** a moved unit whose `depends_on` names a unit of a kept mixed change in `in_review`, or a merged one whose merge is not loaded
- **WHEN** the plan is made
- **THEN** it is an error naming the unit, `depends_on` and the target, the second saying to run a tick

#### Scenario: A staying unit of the moving repo still refuses

- **GIVEN** a moved unit whose `depends_on` names a merged unit of the moving repo that stays for no reason the requirement lists (its change cannot be read, or it blocks the run)
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

### Requirement: An edge that would point at nothing is an error naming it

Before any write, for every moved unit each `depends_on`, `needs` and `superseded_by` id SHALL be a moved unit or already be in the destination, and each `joined` member's change SHALL be a moved active change, a moved archive entry (by its name without the date), a change the moved units carry with no directory, or a change already in the destination (active or archived). The one exception is a dependency on a merged unit that stays for a reason that requirement lists, which the requirement "A dependency on a merged unit of another repo is carried as satisfied history" settles. A `Needs: <change> group <n>` line in a moved `tasks.md` SHALL be held to the same rule at the change level: it is an error, except that when the named change stays for one of those reasons and every unit that builds the named group is `merged` with its merge loaded, it SHALL be a warning naming the change, the group and the target, saying the group is merged history and the line is kept and does nothing in the destination; a group built by no unit, or by a unit that is not merged, is the error, and one merged but not loaded is the error saying to run a tick. The copied `tasks.md` SHALL be byte for byte the source's (apart from `--scrub`); a `Needs:` line is never rewritten or removed. Each failure SHALL be one error line naming the unit or change, the field and the target, all listed together, with exit 1 and nothing written. An edge from a staying unit or change to something moved SHALL be listed as a warning, and as an error under `--remove`, except an edge from a staying unit to a moved unit in state `merged`, which SHALL be a warning under `--remove` as well.

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

- **GIVEN** a moved `tasks.md` with `Needs: other group 2` where `other` stays and no unit builds its group 2
- **WHEN** the plan is made
- **THEN** the error names the change, the line's group and `other`

#### Scenario: A change-level needs on merged history of a kept mixed change

- **GIVEN** a moved change `g` whose group 1 has `Needs: m group 4`, where `m` is a mixed change kept with `--allow-mixed source` and every unit that builds its group 4 is merged and loaded
- **WHEN** the plan is made
- **THEN** it is a warning naming `g`, group 1 and `m`, not an error, and the copied `g/tasks.md` equals the source's

#### Scenario: A change-level needs on a group still being built

- **GIVEN** the same line where the unit that builds `m` group 4 is in `in_review`
- **WHEN** the plan is made
- **THEN** it is an error naming the change, the group and `m`

#### Scenario: The destination reads the kept line as nothing

- **GIVEN** a destination holding the copied `g` and not `m`
- **WHEN** `abk tags g` and the pipeline's `Needs:` linking run over it
- **THEN** `abk tags` reports no problem, no dependency is linked and no unit of `g` waits for the line

#### Scenario: A staying edge into the moved set

- **GIVEN** a staying unit whose `depends_on` names a moved unit that is not merged
- **WHEN** the plan is made without `--remove`
- **THEN** it is a warning, and with `--remove` it is an error

#### Scenario: A staying edge into a moved merged unit

- **GIVEN** a staying unit of another repo whose `depends_on` names a moved merged unit
- **WHEN** the plan is made with `--remove`
- **THEN** it is a warning, and the staying unit's record is not changed
