# Spec Delta

## Purpose

Defines what the adapt step must account for when a unit is replayed onto a changed
predecessor, and what happens when its accounting is incomplete.

## ADDED Requirements

### Requirement: Only tests whose fate is uncertain must be accounted for

The adapt step SHALL require a decision only for the tests the unit added that are missing
from the tree after the replay, or that the replay changed. A test present and unchanged SHALL
count as kept without being mentioned, and the pipeline SHALL determine that itself rather
than asking.

#### Scenario: A test the replay left alone

- **WHEN** a test the unit added is present after the replay and unchanged
- **THEN** no decision is required for it and its absence from the accounting is not a problem

#### Scenario: A test that vanished

- **WHEN** a test the unit added is missing from the tree after the replay
- **THEN** a decision is required, and a retirement must give a reason naming what in the
  predecessor made it invalid

#### Scenario: A test that survived in weakened form

- **WHEN** a test the unit added is present but changed by the replay
- **THEN** a decision is required for it, because a test can be quietly weakened as easily as
  dropped

### Requirement: An incomplete accounting is asked again before the unit fails

When the accounting does not satisfy the check, the pipeline SHALL put the check's own problems
back to the agent, naming what is outstanding, and check again — a small, fixed number of times
— before failing the unit. When it does fail, those problems SHALL be recorded on the unit.

#### Scenario: One decision missing

- **WHEN** the accounting covers every required test but one
- **THEN** the agent is told which is missing and asked for it, and the unit proceeds once the
  accounting is complete

#### Scenario: Still incomplete

- **WHEN** the accounting is still not satisfied after the last attempt
- **THEN** the unit fails, with the outstanding problems on its record rather than only in a log

#### Scenario: What the second ask costs

- **WHEN** the accounting is asked again
- **THEN** the ported code is not rebuilt — only the accounting is outstanding, and the adapt
  commit already stands

### Requirement: The guard against silent drops is unchanged

The pipeline SHALL continue to refuse an accounting that claims to keep a test not in the tree,
that retires a test without a reason, or that leaves a missing or changed test unexplained after
the attempts are spent.

#### Scenario: A keep that is not real

- **WHEN** a decision claims a test was kept and the tree does not contain it
- **THEN** it is a problem, as it is today

#### Scenario: A retirement without a reason

- **WHEN** a test is retired with no reason naming the predecessor's change
- **THEN** it is a problem, as it is today
