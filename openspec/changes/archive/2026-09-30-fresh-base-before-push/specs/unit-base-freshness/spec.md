# Spec Delta

## Purpose

Defines when a unit checks that its branch sits on its base as the remote has
it, and what it does when it does not.

## ADDED Requirements

### Requirement: A run that starts from existing commits fetches before it restacks

When a unit's run begins with commits already on its branch — a resume or a
rework — the runner SHALL fetch the repo's remote before it moves the branch
onto its base, so the move is against the remote as it is at that moment. A
fetch that fails SHALL be logged and SHALL NOT fail the unit.

#### Scenario: A rework that starts late in a tick

- **WHEN** a rework starts after another pull request has merged to the trunk
  since the tick began
- **THEN** the branch is moved onto the trunk including that merge before the
  rework's agent runs

#### Scenario: The fetch fails

- **WHEN** the remote cannot be reached at the start of a run
- **THEN** the failure is logged and the run proceeds on the refs it has

### Requirement: A unit checks its base before every push

Before a unit pushes — to open its pull request or to update it — the runner
SHALL fetch the repo's remote and determine the unit's base afresh, asking the
forge whether a parent's pull request has merged. If the branch does not sit on
that base, the runner SHALL move it before pushing, without an agent call
unless the move conflicts.

#### Scenario: The trunk advanced and the move is clean

- **WHEN** a unit is ready to push and the trunk has commits its branch is not
  on top of, and replaying the unit's commits needs no resolution
- **THEN** the branch is moved, tier 1 runs again, the push proceeds, no agent
  is called and no review round is spent

#### Scenario: A parent merged and the store has not heard

- **WHEN** a unit stacked on a parent is ready to push and the parent's pull
  request has merged without a poll having recorded it
- **THEN** the merge is recorded, the unit is moved onto its new base, and its
  pull request is opened against that base

#### Scenario: The move conflicts

- **WHEN** moving the branch onto its base before a push needs conflict
  resolution
- **THEN** nothing is pushed and the unit is planned to resume at its restack,
  with a note that its base moved before its push

#### Scenario: Tier 1 fails on the new base

- **WHEN** the move is clean and tier 1 then fails
- **THEN** nothing is pushed and the unit is planned for rework with tier 1's
  output as its feedback

### Requirement: A clean move keeps the review's approval

A branch moved onto its base without conflict resolution SHALL keep the
approval recorded for it, at the start of a run and before a push alike. A move
that needed resolution SHALL be reviewed before it is pushed.

#### Scenario: Approved, then moved cleanly

- **WHEN** an approved branch is moved onto an advanced base with no resolution
- **THEN** the moved commit may be pushed without another review

### Requirement: A missing base at open holds the unit

When a pull request cannot be opened because its base branch does not exist on
the forge, the unit SHALL be planned to resume at its restack and SHALL NOT be
recorded as failed. Any other failure to open a pull request SHALL remain a
failure.

#### Scenario: The parent's branch was deleted on merge

- **WHEN** opening a unit's pull request is refused because its base branch is
  gone
- **THEN** the unit is planned to resume at its restack, and its next run moves
  it onto its current base and opens the pull request there
