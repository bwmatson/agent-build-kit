# per-group-commits Specification

## Purpose
TBD - created by archiving change tests-are-stubbed-checked-and-committed-per-group. Update Purpose after archive.

## Requirements

### Requirement: The build commits a tests-then-implementation pair for each task group

In a stubbed build, for each task group a unit builds, in the order the unit lists them, the pipeline SHALL commit the group's stubs
and tests as `test: <group title>` and then its implementation as `feat: <group title>`, where the title is the group's heading title.
Each commit's message SHALL have a body that says why: a fixed sentence saying what the commit holds, then the group's "Done when"
sentence when it has one. The unit trailer SHALL stay. A group's tests commit SHALL be made before its implementation is written,
and the implementation of one group SHALL be committed before the tests of the next are written.

#### Scenario: A unit of two groups

- **GIVEN** a stubbed build of a unit holding groups 1 and 2, titled "Parse the key" and "Use the key"
- **WHEN** it is built
- **THEN** its branch has, in order, `test: Parse the key`, `feat: Parse the key`, `test: Use the key`, `feat: Use the key`, each with a
  body and the unit trailer

#### Scenario: A group with no "Done when" sentence

- **WHEN** a group has none
- **THEN** its commits carry the fixed sentence and no more

#### Scenario: Groups of two changes

- **GIVEN** a unit that carries groups of another change
- **WHEN** it is built
- **THEN** the groups are built in the order the unit lists them, its own change's first, one pair each

### Requirement: Each group's red is checked at its own tests commit

The push gate SHALL, for a stubbed build, require that every `test:` commit is followed directly by a `feat:` commit with the same
title, that each tests commit holds tests and stubs and no other implementation, and that the new tests of each tests commit fail
there for the right reason. A branch that breaks any of these SHALL be refused naming the commit.

#### Scenario: A tests commit followed by another

- **GIVEN** a branch with two `test:` commits in a row
- **WHEN** the push gate runs for a stubbed build
- **THEN** it is refused, naming the second

#### Scenario: A tests commit followed by a differently titled implementation

- **GIVEN** `test: Parse the key` followed by `feat: Use the key`
- **WHEN** the push gate runs
- **THEN** it is refused, naming both titles

#### Scenario: The second group's red

- **GIVEN** a branch whose first pair is correct and whose second tests commit has a test that passes
- **WHEN** the push gate runs
- **THEN** it is refused for the second tests commit, and the first is not reported

### Requirement: A build that stops or restarts resumes at the first group without its pair

A stubbed build SHALL take the group it is on from the branch: the first group, in the unit's order, whose implementation commit is
not there. A run that was killed, a restack, and a requeue SHALL therefore continue at that group, and a unit that has a pair for
every group SHALL go on to its checks. After the last group the build SHALL count the pairs on the branch, and a count short of the
groups SHALL stop the unit naming the groups missing.

#### Scenario: Killed between groups

- **GIVEN** a unit of three groups whose branch holds two complete pairs
- **WHEN** the run is resumed
- **THEN** the tests of the third group are written next and the first two are not written again

#### Scenario: Killed after a tests commit

- **GIVEN** a branch whose last commit is a group's `test:` commit
- **WHEN** the run is resumed
- **THEN** that group's implementation is written, and its tests are not written again

#### Scenario: A short count

- **WHEN** the last group's implementation made no commit
- **THEN** the unit stops naming the group, and nothing is reviewed

### Requirement: Stubbed TDD commits are a setting, and the default is on

The workspace SHALL accept `builders.stubbed_tdd_commits`, a boolean, which turns on stubs, the check loop and per-group commits
together. It SHALL default to on. A workspace that sets it off SHALL get a build with one tests commit and one implementation commit
for the whole unit and no check loop, as before this change.

#### Scenario: The default

- **WHEN** a workspace configures no `builders` section
- **THEN** `stubbed_tdd_commits` is on

#### Scenario: Off

- **GIVEN** `builders.stubbed_tdd_commits: false`
- **WHEN** a unit of three groups is built
- **THEN** its branch holds one `test:` and one `feat:` commit for the whole unit, titled with the unit's title

#### Scenario: A value that is not a boolean

- **WHEN** the setting is a string
- **THEN** loading the configuration fails naming the key

#### Scenario: The old name

- **GIVEN** a workspace file with `builders.per_group_commits: false`
- **WHEN** the configuration is loaded
- **THEN** the setting is read as `stubbed_tdd_commits: false`, `abk config` and `abk doctor` say the old name is deprecated, and `abk config --migrate` rewrites the key

#### Scenario: Both names

- **WHEN** a workspace file sets both `per_group_commits` and `stubbed_tdd_commits`
- **THEN** loading the configuration fails naming both keys
