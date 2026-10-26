## ADDED Requirements

### Requirement: Task progress and follow-ups are tracked in a copy under the state directory

The pipeline SHALL tick and untick task boxes, and record and read a change's follow-ups, in a tracking copy under `<state dir>/changes/<change>/` (`tasks.md` and `follow-ups.md`), and SHALL NOT write the repository's `tasks.md` or `follow-ups.md` while the change is active. The copy SHALL be made from the repository file the first time it is needed, boxes included. Everything that reads the specification (validation, the planner, the group steps, the spec snapshot, the plan's staleness) SHALL keep reading the repository `tasks.md`. A tick SHALL never make a plan stale. The pipeline worktree SHALL have no modified tracked file as a result of a tick, an untick or a recorded follow-up.

#### Scenario: A unit reaching review ticks the copy only

- **GIVEN** a change with a unit that reaches `in_review`
- **WHEN** its groups are marked
- **THEN** the boxes of those groups are `[x]` in the tracking copy, the repository `tasks.md` is byte for byte as before, and `git status` in the worktree shows no change

#### Scenario: A failed unit is unticked in the copy

- **GIVEN** a unit whose groups were ticked in the copy
- **WHEN** it fails
- **THEN** those boxes are `[ ]` in the copy and the repository file is untouched

#### Scenario: The first use makes the copy

- **GIVEN** a repository `tasks.md` with some boxes already ticked and no copy
- **WHEN** a unit's groups are marked
- **THEN** the copy holds the repository text with those boxes as they were, and the unit's boxes set

#### Scenario: Specification readers are unaffected

- **GIVEN** a copy with ticked groups and an unticked repository file
- **WHEN** the plan's staleness, `abk tags` and the group steps are computed
- **THEN** they read the repository file and give the answers they gave before ticking

### Requirement: The copy is reconciled with an edited repository tasks.md

Whenever the copy is written or copied back, it SHALL be rebuilt from the repository file's current text, with each task `N.M` ticked when the copy had it ticked, unticked when the copy had it unticked, and, when the copy did not have it, ticked if every other task of its group is ticked and unticked otherwise. A group the copy lacks SHALL be appended unticked; a group the repository file lacks SHALL be dropped from the copy; every other line SHALL be the repository's. A repository file that cannot be read SHALL leave the copy as it is.

#### Scenario: A group is added

- **GIVEN** a copy with groups 1 and 2 ticked and a repository file that gained a group 3
- **WHEN** the copy is reconciled
- **THEN** groups 1 and 2 are ticked, group 3 is present with its text and unticked

#### Scenario: A group is removed

- **GIVEN** a copy with groups 1 to 3 and a repository file without group 2
- **WHEN** the copy is reconciled
- **THEN** group 2 is gone from the copy and the ticks of groups 1 and 3 are kept

#### Scenario: A task is added to a finished group

- **GIVEN** group 1 fully ticked in the copy and a repository file that adds a task 1.4
- **WHEN** the copy is reconciled
- **THEN** 1.4 is ticked; and with group 1 only partly ticked, 1.4 is unticked

#### Scenario: Text edited by `abk tags --fix`, a `Needs:` line or a rewording

- **GIVEN** a copy with ticks and a repository file whose headings or text changed
- **WHEN** the copy is reconciled
- **THEN** the copy's text is the repository's and the ticks are on the same task numbers

#### Scenario: A renumbered group

- **GIVEN** the repository file's group 2 renumbered 3 while no unit holds either number
- **WHEN** the copy is reconciled
- **THEN** the ticks follow the numbers: 3 has what 3 had, and 2 is gone or new

#### Scenario: The repository file is gone

- **GIVEN** a change withdrawn from the repository
- **WHEN** the copy would be reconciled
- **THEN** it is left as it is and nothing is created

### Requirement: Follow-ups are recorded and read through the copy

`record_follow_ups`, the note of earlier units' follow-ups put in a fresh build's prompt, the unit's follow-ups in its pull request body and the review page SHALL use `<state dir>/changes/<change>/follow-ups.md`; a read SHALL fall back to the repository `follow-ups.md` when the copy does not exist. The block of one unit SHALL still be replaced, not duplicated, by a later record of the same unit. The write fence SHALL stay as it is for build agents, and a track run's grant of Markdown under the state directory SHALL NOT include `<state dir>/changes/`.

#### Scenario: Recorded in the copy and shown in the pull request

- **GIVEN** an approved unit with deferred follow-ups
- **WHEN** they are recorded and the pull request body is built
- **THEN** the copy holds a block `## From \`<unit>\``, the repository change directory has no `follow-ups.md`, and the body lists the items

#### Scenario: A later unit's prompt

- **GIVEN** a copy with an earlier unit's block
- **WHEN** a later unit of the change is built
- **THEN** its prompt carries that block

#### Scenario: A repository file only

- **GIVEN** no copy and a repository `follow-ups.md`
- **WHEN** the follow-ups are read
- **THEN** the repository file's text is what is read

#### Scenario: The fence

- **GIVEN** a build agent, and a track run
- **WHEN** each tries to write `<state dir>/changes/<change>/tasks.md`
- **THEN** both are refused, and a track run's run log under the state directory is still allowed
