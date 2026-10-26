# Spec Delta

## Purpose

Lets a dependency be one that must merge before its dependent starts, in the
same repo as well as across repos.

## ADDED Requirements

### Requirement: A dependency can be required to merge first

A `Needs:` line SHALL accept the qualifier `merged` straight after the group
number. A dependency declared that way SHALL keep its dependent from starting
until the dependency has merged, or has been satisfied with its work landed,
whether or not the two are in the same repo. A `Needs:` line without the
qualifier SHALL keep its present meaning.

#### Scenario: Same repo, required to merge

- **WHEN** a unit needs a same-repo unit `merged`, and that unit is in review
- **THEN** the dependent does not start

#### Scenario: The dependency merges

- **WHEN** that dependency merges
- **THEN** the dependent may start, on the trunk

#### Scenario: Without the qualifier

- **WHEN** a unit needs a same-repo unit without `merged`, and that unit is in
  review
- **THEN** the dependent may start, stacked on the dependency's branch, as
  before

### Requirement: The graph page shows a merge-gated dependency

The unit graph page SHALL draw a dependency that must merge first differently
from the others, and label it, so a unit waiting on a dependency that is
already in review shows why.

#### Scenario: Waiting on a pull request in review

- **WHEN** a unit waits on a merge-gated dependency that is in review
- **THEN** the page draws that edge labelled `merged` and the unit as blocked
