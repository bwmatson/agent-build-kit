## MODIFIED Requirements

### Requirement: A stubbed unit with commits of its own still needs its pairs

When the branch holds at least one commit of its own, a stubbed build SHALL count the pairs after the last group as before and stop the unit when the
branch has no pair for a group, saying "the branch holds no tests and implementation pair for group <n> (<title>)" and naming the first group the
branch has no pair for. A group whose agents leave nothing to commit is recorded with an empty, marked pair when the whole-repository unit tests pass on the
tree (see `built-group-recorded-as-empty-pair`); when they do not pass, the stop is the one above. Setting `produced_nothing` SHALL NOT bypass this count for a
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
