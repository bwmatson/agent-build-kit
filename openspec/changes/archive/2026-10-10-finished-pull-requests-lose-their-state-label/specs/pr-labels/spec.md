## ADDED Requirements

### Requirement: A finished unit's pull request carries no state label

When a unit's stored state becomes merged, closed, satisfied or unplanned and the unit has a pull request, the pipeline SHALL remove every
state label from that pull request. Labels that name the change a pull request belongs to and labels a person added SHALL be left as they are.
The pipeline SHALL read which labels are on the pull request once and remove only the state labels it finds, and a state label that is already
gone SHALL count as removed. Which labels are removed SHALL be decided by the unit's stored state, never by reading a state label back.

#### Scenario: A unit in review merges

- **GIVEN** a unit whose pull request carries the in-review state label
- **WHEN** the unit merges
- **THEN** the pull request carries no state label

#### Scenario: A unit is closed

- **WHEN** a unit's pull request is closed without merging
- **THEN** whatever state label it carried is removed

#### Scenario: A satisfied or unplanned unit with a pull request

- **WHEN** a unit that has a pull request becomes satisfied or unplanned
- **THEN** its state labels are removed

#### Scenario: Labels that are not state labels stay

- **GIVEN** a pull request carrying a change label and a label a person added
- **WHEN** its unit finishes
- **THEN** both are still on it

#### Scenario: A unit with no pull request

- **WHEN** a unit with no pull request finishes
- **THEN** no call is made to the code host

#### Scenario: The label is already gone

- **WHEN** a finished unit's pull request carries no state label
- **THEN** nothing is removed and nothing is reported as a failure

#### Scenario: A host without labels

- **WHEN** a unit finishes in a repository whose host keeps no labels
- **THEN** that is not treated as a fault and is said once

#### Scenario: The host refuses

- **WHEN** reading or removing a label fails as a unit finishes
- **THEN** the failure is logged once and the unit's state is still the finished one

#### Scenario: A merge is delivered twice

- **WHEN** the same merge is recorded a second time
- **THEN** nothing is removed twice and nothing fails

### Requirement: Pull requests already carrying a stale state label are cleaned by the pipeline

Each round of a tick SHALL clear the state labels of the pull requests of units that are merged, closed or satisfied and have not yet been
cleaned, and SHALL record each cleaned pull request in a machine-local record that is read and written under a lock and replaced atomically.
No more than `limits.label_sweep_per_tick` pull requests (default 20) SHALL be handled in a round, lowest pull request number first within each
repository, and the log SHALL say how many remain. A pull request is recorded when it was cleared or had nothing to clear, including where its
host keeps no labels; it SHALL NOT be recorded when clearing failed, and SHALL be tried again. The sweep SHALL run after the poll and before
builds are chosen, SHALL NOT delay a build, and SHALL NOT need a command or a new field in the unit store. Losing the record SHALL cost only a
further pass.

#### Scenario: A merged unit's pull request is still labelled in review

- **WHEN** a round finds a merged unit whose pull request still carries the in-review label and is not recorded
- **THEN** the label is removed and the pull request is recorded

#### Scenario: A pull request that is already clean

- **WHEN** a round finds a finished unit whose pull request carries no state label
- **THEN** it is recorded and nothing is removed

#### Scenario: A pull request already recorded

- **WHEN** a pull request is recorded as cleaned
- **THEN** later rounds do not visit it

#### Scenario: The per-round bound

- **GIVEN** more unrecorded finished pull requests than the limit
- **WHEN** a round runs
- **THEN** only the limit's number are handled, lowest number first, the log says how many remain, and the next round handles the rest

#### Scenario: A clear fails

- **WHEN** reading or removing a label fails for a pull request
- **THEN** it is not recorded and a later round tries it again

#### Scenario: The record is lost

- **WHEN** the record is deleted or cannot be read
- **THEN** it is treated as empty, each pull request is found clean and recorded again, and nothing else is affected

#### Scenario: A host without labels

- **WHEN** a round reaches a repository whose host keeps no labels
- **THEN** its pull requests are recorded without any removal and are not visited again

#### Scenario: A failure in the sweep

- **WHEN** the sweep raises
- **THEN** it is logged and the rest of the round and every build proceed as they would have

#### Scenario: A closed pull request is reopened

- **WHEN** a pull request of a closed unit is reopened and its unit changes state
- **THEN** the state label for its new state is set as for any change, and the earlier record does not stop the later finish from being cleared
