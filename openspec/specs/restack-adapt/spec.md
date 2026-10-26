# restack-adapt Specification

## Purpose
Defines what the adapt step must account for when a unit is replayed onto a changed
predecessor, and what happens when its accounting is incomplete.

## Requirements

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

### Requirement: A unit's tests are those its changes defined or touched

The tests a unit is asked to account for SHALL be those whose definition its own changes added or
removed, together with those whose body its changes edited. A test that appears in the unit's diff
only as surrounding context SHALL NOT count as the unit's.

#### Scenario: A test the unit wrote

- **WHEN** the unit's changes add a test definition
- **THEN** that test is among the ones it must account for

#### Scenario: A test the unit deleted

- **WHEN** the unit's changes remove a test definition
- **THEN** it is still among them, because a deletion is what the accounting exists to catch

#### Scenario: A test the unit weakened

- **WHEN** the unit's changes edit a line inside a test it did not define
- **THEN** that test is among them, because weakening another's test carries the same risk

#### Scenario: A test that merely sits nearby

- **WHEN** a test definition appears in the unit's diff only on a context line
- **THEN** it is not among them, and no decision is required for it

### Requirement: The accounting names what is outstanding

When the accounting is not satisfied, the problems recorded SHALL name the tests still
outstanding, so that an operator reading a failed unit sees which tests are in question.

#### Scenario: A failed accounting

- **WHEN** a unit fails for an incomplete accounting
- **THEN** its record names the outstanding tests rather than only that something was missing

### Requirement: The port is the last step of the conflict step, in the same session

The port SHALL be the last step of the order a conflict is settled in, started only when the narrower steps have failed their checks. It
SHALL be a call of the session those steps ran in, and SHALL be told which of them were tried and what their checks said, in addition to
what it is told today. The accounting, its check and its bounded asks SHALL apply to it and SHALL NOT apply to a conflict the narrower
steps settled. A session that cannot be continued SHALL be replaced by a new one given the full prompt, with no error. A conflict the
port does not settle SHALL fail as it does today, with the outstanding tests on the unit's record.

#### Scenario: A conflict that needs a port escalates in the same session

- **GIVEN** a conflict whose first two steps failed their checks
- **WHEN** the port starts
- **THEN** it runs in the same session, the old work is kept under a reference and the branch is reset onto the new base, and the prompt says what was tried

#### Scenario: The accounting applies to the port only

- **GIVEN** a conflict settled by the first step
- **WHEN** the move completes
- **THEN** no decision is asked for any of the unit's tests

#### Scenario: The session is gone

- **GIVEN** a session the runtime cannot continue
- **WHEN** the port starts
- **THEN** it runs in a new session with its full prompt

#### Scenario: The port fails its accounting

- **WHEN** the accounting is still incomplete after its last ask
- **THEN** the unit fails with the outstanding tests on its record, as before
