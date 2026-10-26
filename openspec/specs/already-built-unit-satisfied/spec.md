# already-built-unit-satisfied Specification

## Purpose
TBD - created by archiving change a-group-already-built-is-satisfied-in-a-stubbed-build. Update Purpose after archive.

## Requirements

### Requirement: A stubbed unit with no commit of its own is satisfied

In a stubbed build (`builders.per_group_commits` on, the repo's profile supporting stubs), after a group's implementation step the pipeline SHALL
count the commits the unit's branch carries beyond its base. When the count is zero it SHALL NOT stop the unit for a missing tests and implementation
pair, SHALL record `produced_nothing`, and the unit SHALL follow the route a unit with nothing of its own takes in a build that is not stubbed: after
the last group the whole-repository unit tests run, and a pass ends the unit `satisfied` with nothing committed, pushed or opened and any open pull
request closed. The state, the note and the closing SHALL be the existing ones of the `satisfied` step. A failing unit test SHALL take the existing
failure route.

#### Scenario: Every group already built, the checks pass

- **GIVEN** a stubbed unit whose groups' work is already on its base and whose agents commit nothing
- **WHEN** it is built
- **THEN** it ends `satisfied` with the note "nothing to add and unit-test passes — satisfied", the branch holds no commit, nothing is pushed and no pull request is opened

#### Scenario: Already built but the unit tests fail

- **GIVEN** the same unit whose whole-repository unit tests fail
- **WHEN** it is built
- **THEN** it takes the existing failure route: it stops with "unit-test failed" and the output is saved as feedback with the source `unit-test`

#### Scenario: The stubbed and the old build agree

- **GIVEN** one branch with no commit of its own, built once with the setting on and once with it off
- **WHEN** each build ends
- **THEN** both end in the state `satisfied` with the same note

#### Scenario: A resumed run of a zero-commit unit

- **GIVEN** a unit stopped earlier with a pair message, whose branch holds no commit of its own, requeued
- **WHEN** it is resumed
- **THEN** it is built from its first group, finds no commit of its own and ends `satisfied`

#### Scenario: A unit of only test-only groups with no commit

- **GIVEN** a unit whose groups are all test-only and whose tests agent writes nothing, so no `test:` commit exists
- **WHEN** the groups are counted after the last group
- **THEN** the count is skipped, `produced_nothing` is set and the unit ends `satisfied`; a test-only group whose `test:` commit exists has a commit of its own and is counted as before

### Requirement: A stubbed unit with commits of its own still needs its pairs

When the branch holds at least one commit of its own, a stubbed build SHALL count the pairs after the last group as before and stop the unit when the
branch has no pair for a group, saying "the branch holds no tests and implementation pair for group <n> (<title>)" and naming the first group the
branch has no pair for; when the branch holds a `feat:` commit of that group where its `test:` was expected, it SHALL say instead "a feat: commit for group <n> has no test: commit before it",
followed by that subject in parentheses. A group whose agents leave nothing to commit is recorded with an empty, marked pair when the whole-repository unit tests pass on the
tree (see `built-group-recorded-as-empty-pair`), as is a group whose tests agent writes no new tests (an empty marked `test:`) and a group with real, passing tests and no implementation change
(an empty marked `feat:`); when the tests do not pass, the stop is the one above. Setting `produced_nothing` SHALL NOT bypass this count for a
branch with commits. A unit built without stubs SHALL be as before.

#### Scenario: Some commits but a missing pair

- **GIVEN** a stubbed unit of three groups whose third implementation made no commit and whose unit tests fail
- **WHEN** the pairs are counted
- **THEN** the unit stops with "the branch holds no tests and implementation pair for group 3" and is not sent to the unit tests as having produced nothing

#### Scenario: Some commits, a missing pair and passing tests

- **GIVEN** a stubbed unit of three groups whose third group's agents made no commit and whose unit tests pass
- **WHEN** the pairs are counted
- **THEN** group 3 is recorded with an empty marked pair and the unit goes on to checks

#### Scenario: A mixed unit still stops

- **GIVEN** a stubbed unit whose first group was built on the base and whose second group commits a pair
- **WHEN** the pairs are counted after the last group
- **THEN** the unit stops with the pair message naming group 1, as before this change it stopped with a pair message

#### Scenario: A lone implementation commit is named

- **GIVEN** a stubbed unit whose branch reads `test g3, feat g3, feat g4`
- **WHEN** the pairs are counted for group 4
- **THEN** the unit stops with "a feat: commit for group 4 has no test: commit before it (feat: <group 4 title>)"
