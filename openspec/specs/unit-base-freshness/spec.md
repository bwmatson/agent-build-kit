# unit-base-freshness Specification

## Purpose
Defines when a unit checks that its branch sits on its base as the remote has
it, and what it does when it does not.

## Requirements

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
unless the move conflicts. The unit-test that follows a clean move SHALL be the
one the requirement "A clean move is checked by what it can affect" describes.

#### Scenario: The trunk advanced and the move is clean

- **WHEN** a unit is ready to push and the trunk has commits its branch is not
  on top of, and replaying the unit's commits needs no resolution
- **THEN** the branch is moved, unit-test runs again, the push proceeds, no agent
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

#### Scenario: Unit-test fails on the new base

- **WHEN** the move is clean and unit-test then fails
- **THEN** nothing is pushed and the unit is planned for rework with unit-test's
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

### Requirement: A clean move is checked by what it can affect

After a branch is moved onto a new base with no conflict, no resolution and an unchanged diff, whether before a push or when a merge releases a
dependent, unit-test SHALL run lint on the moved diff as it does for every run, then only the tests the move can affect, unless the setting
`limits.restack_check` is `full`. Those tests are the union of the tests the unit added or changed, and the tests the toolchain profile's
`affected_test_commands` names for the unit's own files together with the files the move brought in. The framework outside the profiles SHALL NOT
name an ecosystem or read an import graph. The full suite SHALL run in its place when a file the move brought in is also a file the unit
changes, when the profile cannot select for any project or cannot place a changed file, when a selected command cannot run, or when the unit
produced nothing of its own. Every other run of unit-test SHALL be unchanged, and the full suite SHALL remain in CI on every pull request.

#### Scenario: A move over disjoint files

- **GIVEN** a unit that changes `a.x` and its test, and a base that moved by changing only `b.x`, which no test of the unit's reaches
- **WHEN** the branch is moved cleanly and unit-test runs
- **THEN** lint runs on the moved diff and only the unit's own tests and the tests the profile names for those files run, not the full suite

#### Scenario: A move over files the unit's code depends on

- **GIVEN** a unit that changes `a.x`, which imports `c.x`, and a base that moved by changing `c.x`
- **WHEN** the branch is moved cleanly and unit-test runs
- **THEN** the tests that import `c.x` are among those run, as well as the unit's own

#### Scenario: A semantic conflict with no textual overlap is caught

- **GIVEN** a base that changed the signature of a function in `c.x`, and a unit that calls that function from `a.x` with the old signature, so
  that no path is changed by both
- **WHEN** the branch is moved cleanly and unit-test runs
- **THEN** the test that runs the call is selected, fails, and the unit is not pushed on the move

#### Scenario: A move that touched the unit's own file keeps the full suite

- **GIVEN** a base that moved by changing a file the unit also changes, and git merged the two cleanly
- **WHEN** unit-test runs on the moved branch
- **THEN** the full suite runs, and the log says a file the unit changes was brought in

#### Scenario: A profile that cannot select runs the full suite

- **GIVEN** a profile that answers nothing, or that cannot place one of the changed files, or a selected command that cannot start
- **WHEN** unit-test runs on a moved branch
- **THEN** the full suite runs and the log says why

#### Scenario: A resolved conflict or a changed diff is not scoped

- **GIVEN** a move that needed resolution, or one that changed the unit's diff
- **WHEN** the unit's checks run
- **THEN** they run as today in full, and the review rule for such a move is unchanged

#### Scenario: The setting restores full runs

- **GIVEN** `limits.restack_check` set to `full`
- **WHEN** a branch is moved cleanly and unit-test runs
- **THEN** the full suite runs exactly as before this requirement, and a value other than `affected` or `full` is refused when the configuration loads

#### Scenario: Default

- **GIVEN** a configuration that does not set `limits.restack_check`
- **WHEN** a branch is moved cleanly
- **THEN** the selected run is made

#### Scenario: The merge handler's move is scoped the same way

- **GIVEN** a merge that releases a dependent, whose branch the handler moves cleanly
- **WHEN** the handler runs unit-test before it pushes
- **THEN** it applies the same rule, with the old base it already holds

#### Scenario: Other runs of unit-test are unchanged

- **GIVEN** the first check of a unit, a fix round, the gate before review, and a unit that produced nothing
- **WHEN** unit-test runs
- **THEN** each runs exactly as before this requirement

#### Scenario: E2e-test is unchanged

- **GIVEN** an e2e-test unit whose base moved cleanly
- **WHEN** the unit is checked after the move
- **THEN** its unit-test is scoped as above, then e2e-test runs again on the moved commit as before, and e2e-test is never scoped, repeated or isolated by this requirement

#### Scenario: The log says what ran

- **GIVEN** a scoped run that ran 14 tests of 5963, six of them the unit's own and eight selected for the move
- **WHEN** the run is logged
- **THEN** the unit's log holds `moved base: ran 14 of 5963 tests (own 6, affected 8)`, and a run that fell back to the full suite names the reason instead

### Requirement: A failed scoped test is isolated before the unit is held

When the scoped unit-test of a moved base fails, the failed tests SHALL be run again alone and serially by the same isolation unit-test already uses
for the full suite, before anything is held. A test that fails again, or that the unit added or changed, SHALL hold the unit exactly as a unit-test
failure does today, with the failure as its feedback. A test that passes alone is a flake on the moved base: it SHALL be recorded and its one fix
change written as for any flake, and the unit SHALL NOT wait for that change nor be held for it. E2e-test SHALL NOT be repeated or isolated.

#### Scenario: A flake on the moved base does not hold

- **GIVEN** a scoped run in which a test the unit did not add or change fails, and passes when run alone
- **WHEN** the failure is classified
- **THEN** the flake is recorded, the unit is not held, gains no `Needs:` line and goes on to its push

#### Scenario: A failure that repeats holds

- **GIVEN** a scoped run in which a test fails, and fails again alone
- **WHEN** the failure is classified
- **THEN** nothing is pushed and the unit is held as today with the failure's output as its feedback

#### Scenario: A test the unit added is never excused

- **GIVEN** a scoped run in which a test the unit added fails and passes alone
- **WHEN** the failure is classified
- **THEN** the unit is held as for a real failure

#### Scenario: A full run keeps its flake rule

- **GIVEN** a full run of unit-test, on a moved base under `limits.restack_check: full` or at any other check
- **WHEN** a test fails and passes alone
- **THEN** the flake is recorded and the unit waits for its fix change, as before this requirement
