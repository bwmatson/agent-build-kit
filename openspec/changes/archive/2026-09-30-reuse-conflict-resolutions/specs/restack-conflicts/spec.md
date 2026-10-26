# Spec Delta

## Purpose

Defines that a conflict the pipeline has already resolved is replayed rather than re-derived,
and that a replayed resolution is confirmed before it is used.

## ADDED Requirements

### Requirement: A conflict resolved once is replayed when it recurs

The pipeline SHALL record how a restack's conflicts were resolved and SHALL replay a recorded
resolution when the same conflict appears again, for every unit of the repository — relying on
the cache git keeps in the repository's common directory rather than copying anything between
worktrees.

#### Scenario: The same hunk in a later unit

- **WHEN** a restack of one unit hits a conflict already resolved while restacking another unit
  of the same repository
- **THEN** the recorded resolution is applied to the file, rather than the conflict being
  derived again

#### Scenario: A conflict never seen before

- **WHEN** a conflict has no recorded resolution
- **THEN** it is resolved as it is today

### Requirement: A replayed resolution is left for confirmation, not staged

A replayed resolution SHALL be written into the working tree but SHALL NOT be staged, and its
path SHALL remain unmerged, so that no recorded resolution reaches a commit without something
looking at it. The resolver SHALL be told which paths carry a replayed resolution, and SHALL
stage it, correct it, or say that it was wrong.

#### Scenario: The resolution is right

- **WHEN** the resolver examines a replayed resolution and agrees with it
- **THEN** it stages it and the rebase continues

#### Scenario: The resolution is wrong

- **WHEN** the resolver judges a replayed resolution incorrect
- **THEN** it resolves the path itself, and that resolution is what is recorded

#### Scenario: Nothing passes unexamined

- **WHEN** a restack completes with replayed resolutions among its conflicts
- **THEN** each of them was staged deliberately rather than automatically

### Requirement: The operator's checkout is not reconfigured

The pipeline SHALL apply this to its own git invocations rather than by writing the setting into
the repository's stored configuration, so that an operator working in the same checkout is
unaffected unless they enable it themselves.

#### Scenario: A human in the same checkout

- **WHEN** an operator rebases in the repository the pipeline builds in
- **THEN** their git behaves as they configured it, not as the pipeline configured it

### Requirement: Unchanged elsewhere

This SHALL apply only to conflicts during a restack. The step that ports a unit onto a
predecessor it could not be replayed onto SHALL be unaffected, as SHALL every other step.

#### Scenario: A unit that has to be ported

- **WHEN** a unit cannot be replayed and is ported instead
- **THEN** nothing about that step changes
