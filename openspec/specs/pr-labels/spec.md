# pr-labels Specification

## Purpose
Defines what a pull request's labels say about its unit: the state the pipeline
maintains, the instructions a person gives, and which of those is consumed.

## Requirements

### Requirement: A pull request carries its unit's state as a label

The pipeline SHALL maintain one label on each of its pull requests naming the
unit's current state, and SHALL replace it when the state changes so that exactly
one such label is present at a time. States with no pull request, and states the
host already shows on a pull request, SHALL NOT have labels.

#### Scenario: A unit moves through its states

- **WHEN** a unit starts building, reaches review, is sent back for rework, and is
  then held
- **THEN** its pull request carries exactly one state label at each point, naming
  that state, with the previous one removed

#### Scenario: A state the host already shows

- **WHEN** a unit merges or its pull request is closed
- **THEN** no state label is added for it

### Requirement: The labels and the unit graph share one vocabulary

The state names and the colours used for labels SHALL be the same ones the unit
graph uses, held in one definition that both the graph and the labels read, so
neither can be renamed or recoloured without the other following. That vocabulary
SHALL include the states the graph derives from a unit's history — waiting on a
dependency, stopped before a rework, stopped for a spent usage window — and not only
the states the unit store records, because those distinctions are what tell a
reader why a unit is not moving.

Where a host renders a label as a single colour, the colour used SHALL be the one
the graph draws a state's outline with, not the pale fill it shades the node with.

#### Scenario: A state the graph can draw

- **WHEN** the graph can draw a state
- **THEN** either a label of the same name and colour exists for it, or it is one of
  the documented states deliberately left unlabelled

#### Scenario: A state is renamed or recoloured

- **WHEN** a state's name or colour changes in the shared vocabulary
- **THEN** both the graph and the labels change with it, with nothing to update
  twice

#### Scenario: Why a unit is not moving

- **WHEN** a unit is waiting on a dependency, stopped before a rework, or stopped
  because a usage window is spent
- **THEN** its label says which, rather than all three reading the same

### Requirement: What a person writes is told apart from what the pipeline writes

The labels a person adds to instruct the pipeline SHALL be distinguishable by name
from the labels the pipeline maintains, and the pipeline SHALL NOT treat a label it
wrote as an instruction.

#### Scenario: The pipeline labels a pull request

- **WHEN** the pipeline sets or replaces a state label
- **THEN** no rework, hold or other dispatch follows from that label appearing

### Requirement: An instruction to rework is consumed when it is acted on

When the pipeline dispatches a rework because a person asked for one with a label,
it SHALL remove that label, so that the pull request reflects its state rather than
an outstanding request, and so that the same instruction can be given again.

#### Scenario: A rework is requested and dispatched

- **WHEN** a person adds the rework label and the pipeline sends the unit back
- **THEN** the label is removed, and the pull request instead carries the state
  label for being reworked

#### Scenario: Asking twice

- **WHEN** a person adds the rework label again after an earlier one was consumed
- **THEN** a new rework is dispatched

#### Scenario: A hold is not consumed

- **WHEN** a person adds the hold label
- **THEN** it remains until a person removes it, because it withdraws the unit for
  as long as it is present rather than requesting a single action

### Requirement: Labelling is cosmetic and never costs a unit

A label the repository lacks SHALL be created once, with a description of what it
means. A failure to read, create, set or remove any label SHALL be logged once and
otherwise ignored: it SHALL NOT fail, hold or delay a unit, and no decision SHALL
be made by reading a state label back — the unit store remains the source of truth.

#### Scenario: A repository without the labels

- **WHEN** the pipeline first labels a pull request in a repository that has none
  of these labels
- **THEN** they are created with their descriptions and applied

#### Scenario: The host refuses

- **WHEN** a label call fails for any reason
- **THEN** the unit proceeds exactly as it would have, and the failure is logged
  once

#### Scenario: Nothing reads it back

- **WHEN** the pipeline decides what to do with a unit
- **THEN** it reads the unit store, not the pull request's state label

### Requirement: A unit in review reads checking while its checks run

A unit in review SHALL be shown as `checking` while any of its pull request's checks is pending, or
while it has none within `limits.checks_register_seconds` of its last push, and as `in_review` once its
checks have passed or that window has ended with none. The status SHALL be derived, SHALL count as in
review for scheduling, and SHALL be what the status command, the graph and the state label show. The
status command SHALL list a checking unit with its pull request link as it lists one awaiting review.

#### Scenario: Checks are running

- **GIVEN** a unit in review with a pending check
- **WHEN** its status is read
- **THEN** it is `checking` and the status command lists it with its pull request link

#### Scenario: Checks passed

- **WHEN** every check has passed
- **THEN** the unit reads `in_review` and is listed as awaiting review

#### Scenario: Just pushed, no checks yet

- **GIVEN** a unit pushed seconds ago whose pull request has no checks
- **WHEN** its status is read
- **THEN** it is `checking`

#### Scenario: A repo with no checks

- **GIVEN** a pull request with no checks, pushed longer ago than the window
- **WHEN** its status is read
- **THEN** it reads `in_review`

#### Scenario: Scheduling is unchanged

- **WHEN** a unit is checking
- **THEN** it holds a queue place and releases its dependents exactly as one in review does

### Requirement: A running unit says whether it is building, reworking or rebasing

A unit that is running SHALL be shown as `rebasing` when its last event is a conflict or a moved
base, as `reworking` when it is answering review or check feedback, and as `running` otherwise. The
status SHALL be derived from the unit's record, SHALL be what the status command, the graph and the
state label show, and SHALL NOT be stored as a state.

#### Scenario: A rework for a conflict

- **GIVEN** a running unit whose rework was requested for a merge conflict
- **WHEN** its status is read
- **THEN** it is `rebasing`

#### Scenario: A rework for a comment

- **GIVEN** a running unit whose rework was requested by a review comment or failing check
- **WHEN** its status is read
- **THEN** it is `reworking`

#### Scenario: A first build

- **GIVEN** a running unit with no feedback
- **WHEN** its status is read
- **THEN** it is `running`

#### Scenario: Nothing is stored

- **WHEN** a unit's record is read
- **THEN** its state is `running` for all three

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
