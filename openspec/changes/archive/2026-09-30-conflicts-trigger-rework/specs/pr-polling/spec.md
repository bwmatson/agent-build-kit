# Spec Delta

## Purpose

Defines that a pull request which can no longer be merged is a signal the
pipeline acts on, and how it is told apart from a host that has not answered yet.

## ADDED Requirements

### Requirement: The poll asks whether a pull request can be merged

Each poll SHALL read whether the host considers the pull request mergeable,
alongside the checks, reviews and comments it already reads, and SHALL keep that
answer in the snapshot it compares against.

#### Scenario: Mergeability is part of the snapshot

- **WHEN** an open pull request is polled
- **THEN** whether it can be merged is recorded with the rest of its state

### Requirement: Becoming unmergeable sends a unit back for rework

When a pull request transitions into a state where the host reports it cannot be
merged, the pipeline SHALL send that unit back for rework, so that its branch is
rebased onto its current base and reviewed again before it is pushed. A pull
request already known to be unmergeable SHALL NOT be dispatched again on later
polls.

#### Scenario: A branch that has gone stale behind a moving trunk

- **WHEN** a unit's branch becomes unmergeable after other work merged
- **THEN** the unit is sent back for rework, rebased and re-reviewed

#### Scenario: Still unmergeable on the next poll

- **WHEN** a unit already dispatched for a conflict is polled again and is still
  unmergeable
- **THEN** nothing further is dispatched

### Requirement: An unanswered mergeability is not a conflict

Where the host has not determined mergeability — which it reports routinely for a
short time after any push, including the pipeline's own — the pipeline SHALL NOT
treat that as a conflict, SHALL dispatch nothing, and SHALL ask again on the next
poll.

#### Scenario: Just after the pipeline pushed

- **WHEN** a poll finds mergeability undetermined shortly after a push
- **THEN** no rework is dispatched and the answer is sought again next poll

#### Scenario: Undetermined then mergeable

- **WHEN** an undetermined answer is followed by a mergeable one
- **THEN** no rework was dispatched at any point

### Requirement: The review queue shows what cannot be merged

Where the pipeline reports the pull requests awaiting review, an entry the host
says cannot be merged SHALL be marked as such, so that the queue a person works
from distinguishes what they can act on.

#### Scenario: Reporting the queue

- **WHEN** the pipeline's status is printed with an unmergeable pull request
  awaiting review
- **THEN** that entry says it cannot be merged
