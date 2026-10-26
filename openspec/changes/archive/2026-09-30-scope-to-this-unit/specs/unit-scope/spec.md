# Spec Delta

## Purpose

Defines that a unit builds and is reviewed against its own task groups, not the change's
remaining work, and what becomes of a unit whose groups are already implemented.

## ADDED Requirements

### Requirement: A build run is told which groups are not its own

A build run SHALL be told, alongside its own task groups, which groups the later units of
its change will cover, and SHALL be instructed to implement only its own — including when
a later group's work is adjacent or nearly free — with the reason given: each unit is one
pull request a person reads, and work pulled forward makes it larger and the change's
record of what remains wrong.

#### Scenario: The next group is one edit away

- **WHEN** a build run could implement the following group with little extra work
- **THEN** it is instructed not to, and the instruction says why

#### Scenario: The plan is still visible

- **WHEN** a build run reads its change's tasks
- **THEN** it sees the whole plan, with its own groups and the later ones distinguished

### Requirement: A review does not require work from a later group

A review of a unit SHALL be told the same boundary, and a finding whose fix belongs to a
later group SHALL be reported as belonging there rather than required of this unit. Every
finding about the unit's own groups SHALL keep its current force.

#### Scenario: A finding that belongs later

- **WHEN** a reviewer finds work that a later group of the change will cover
- **THEN** it says so and does not block approval on it

#### Scenario: A finding about this unit

- **WHEN** a reviewer finds a problem in the unit's own groups
- **THEN** nothing about how it is raised or enforced changes

### Requirement: A unit whose groups are already implemented is satisfied, not failed

When a unit's step produces nothing and the unit has added no commits of its own while the
repository's tier-1 checks pass at its tip, the unit SHALL end in a state recording that
its work arrived by another route: its task groups SHALL be ticked, its dependents SHALL
stop waiting for it, it SHALL NOT be given a pull request, and it SHALL NOT appear among
failed units. This SHALL be judged from the branch and the checks, never from the run's
own account of itself.

#### Scenario: A predecessor did the work

- **WHEN** a unit finds its groups already implemented, has no commits of its own, and the
  checks pass
- **THEN** it is recorded as satisfied, its groups are ticked, and no pull request is
  opened

#### Scenario: Nothing committed and the checks fail

- **WHEN** a unit has no commits of its own and the checks do not pass
- **THEN** it is a failure, as it is today

#### Scenario: Partly done

- **WHEN** a unit has commits of its own and finds the remainder already implemented
- **THEN** it goes to review as usual, because it has a diff to review

### Requirement: A satisfied unit's open pull request is closed with the reason on it

When a unit becomes satisfied and already has an open pull request, the pipeline SHALL post the
reason on that pull request and then close it, so that the explanation is never missing. The
reason SHALL name the groups the unit covered, say that they were implemented elsewhere, and name
where the work landed where that can be determined. Neither the judgement nor the text SHALL
require a language-model call: the judgement is the branch and the checks, and the text is
composed by the pipeline as pull request bodies already are.

#### Scenario: Satisfied after its pull request was opened

- **WHEN** a unit with an open pull request becomes satisfied
- **THEN** the reason is posted on that pull request and the pull request is then closed

#### Scenario: No model is asked

- **WHEN** a satisfied unit's pull request is closed
- **THEN** no language-model call is made to decide it or to write the reason

#### Scenario: Satisfied before any pull request exists

- **WHEN** a unit becomes satisfied and has no pull request
- **THEN** none is opened, and nothing is posted or closed

#### Scenario: The host refuses the close

- **WHEN** posting the reason or closing the pull request fails
- **THEN** the failure is recorded, the unit stays satisfied, and its state is not revisited
