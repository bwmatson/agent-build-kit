## MODIFIED Requirements

### Requirement: A unit checks its base before every push

Before a unit pushes — to open its pull request or to update it — the runner
SHALL fetch the repo's remote and determine the unit's base afresh, asking the
forge whether a parent's pull request has merged. If the branch does not sit on
that base, the runner SHALL move it before pushing, without an agent call
unless the move conflicts. The tier 1 that follows a clean move SHALL be the
one the requirement "A clean move is checked by what it can affect" describes.

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

## ADDED Requirements

### Requirement: A clean move is checked by what it can affect

After a branch is moved onto a new base with no conflict, no resolution and an unchanged diff, whether before a push or when a merge releases a
dependent, tier 1 SHALL run lint on the moved diff as it does for every run, then only the tests the move can affect, unless the setting
`limits.restack_check` is `full`. Those tests are the union of the tests the unit added or changed, and the tests the toolchain profile's
`affected_test_commands` names for the unit's own files together with the files the move brought in. The framework outside the profiles SHALL NOT
name an ecosystem or read an import graph. The full suite SHALL run in its place when a file the move brought in is also a file the unit
changes, when the profile cannot select for any project or cannot place a changed file, when a selected command cannot run, or when the unit
produced nothing of its own. Every other run of tier 1 SHALL be unchanged, and the full suite SHALL remain in CI on every pull request.

#### Scenario: A move over disjoint files

- **GIVEN** a unit that changes `a.x` and its test, and a base that moved by changing only `b.x`, which no test of the unit's reaches
- **WHEN** the branch is moved cleanly and tier 1 runs
- **THEN** lint runs on the moved diff and only the unit's own tests and the tests the profile names for those files run, not the full suite

#### Scenario: A move over files the unit's code depends on

- **GIVEN** a unit that changes `a.x`, which imports `c.x`, and a base that moved by changing `c.x`
- **WHEN** the branch is moved cleanly and tier 1 runs
- **THEN** the tests that import `c.x` are among those run, as well as the unit's own

#### Scenario: A semantic conflict with no textual overlap is caught

- **GIVEN** a base that changed the signature of a function in `c.x`, and a unit that calls that function from `a.x` with the old signature, so
  that no path is changed by both
- **WHEN** the branch is moved cleanly and tier 1 runs
- **THEN** the test that runs the call is selected, fails, and the unit is not pushed on the move

#### Scenario: A move that touched the unit's own file keeps the full suite

- **GIVEN** a base that moved by changing a file the unit also changes, and git merged the two cleanly
- **WHEN** tier 1 runs on the moved branch
- **THEN** the full suite runs, and the log says a file the unit changes was brought in

#### Scenario: A profile that cannot select runs the full suite

- **GIVEN** a profile that answers nothing, or that cannot place one of the changed files, or a selected command that cannot start
- **WHEN** tier 1 runs on a moved branch
- **THEN** the full suite runs and the log says why

#### Scenario: A resolved conflict or a changed diff is not scoped

- **GIVEN** a move that needed resolution, or one that changed the unit's diff
- **WHEN** the unit's checks run
- **THEN** they run as today in full, and the review rule for such a move is unchanged

#### Scenario: The setting restores full runs

- **GIVEN** `limits.restack_check` set to `full`
- **WHEN** a branch is moved cleanly and tier 1 runs
- **THEN** the full suite runs exactly as before this requirement, and a value other than `affected` or `full` is refused when the configuration loads

#### Scenario: Default

- **GIVEN** a configuration that does not set `limits.restack_check`
- **WHEN** a branch is moved cleanly
- **THEN** the selected run is made

#### Scenario: The merge handler's move is scoped the same way

- **GIVEN** a merge that releases a dependent, whose branch the handler moves cleanly
- **WHEN** the handler runs tier 1 before it pushes
- **THEN** it applies the same rule, with the old base it already holds

#### Scenario: Other runs of tier 1 are unchanged

- **GIVEN** the first check of a unit, a fix round, the gate before review, and a unit that produced nothing
- **WHEN** tier 1 runs
- **THEN** each runs exactly as before this requirement

#### Scenario: Tier 2 is unchanged

- **GIVEN** a tier 2 unit whose base moved cleanly
- **WHEN** the unit is checked after the move
- **THEN** its tier 1 is scoped as above, then tier 2 runs again on the moved commit as before, and tier 2 is never scoped, repeated or isolated by this requirement

#### Scenario: The log says what ran

- **GIVEN** a scoped run that ran 14 tests of 5963, six of them the unit's own and eight selected for the move
- **WHEN** the run is logged
- **THEN** the unit's log holds `moved base: ran 14 of 5963 tests (own 6, affected 8)`, and a run that fell back to the full suite names the reason instead

### Requirement: A failed scoped test is isolated before the unit is held

When the scoped tier 1 of a moved base fails, the failed tests SHALL be run again alone and serially by the same isolation tier 1 already uses
for the full suite, before anything is held. A test that fails again, or that the unit added or changed, SHALL hold the unit exactly as a tier 1
failure does today, with the failure as its feedback. A test that passes alone is a flake on the moved base: it SHALL be recorded and its one fix
change written as for any flake, and the unit SHALL NOT wait for that change nor be held for it. Tier 2 SHALL NOT be repeated or isolated.

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

- **GIVEN** a full run of tier 1, on a moved base under `limits.restack_check: full` or at any other check
- **WHEN** a test fails and passes alone
- **THEN** the flake is recorded and the unit waits for its fix change, as before this requirement
