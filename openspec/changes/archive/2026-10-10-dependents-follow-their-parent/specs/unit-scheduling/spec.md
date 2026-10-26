## ADDED Requirements

### Requirement: A unit in review follows its predecessor when the predecessor's branch is changing

On every pass, a unit in review SHALL be set back to `planned` with the cause `upstream_went_back`
and a note naming the predecessor when a same-repo predecessor is not in review, merged or satisfied
and its branch is changing. A branch SHALL be changing when it has commits beyond the unit's last
pushed head, or the unit is being rebased, or the unit is itself waiting on a changing upstream. The
move SHALL be delivered to the unit's thread as an event, not made in the store alone. The
unit's approval, branch, pull request and thread SHALL be kept, a chain of dependents SHALL move in
one pass, and a branch whose claim is held SHALL be left for the next pass.

#### Scenario: A predecessor is reworked and commits

- **GIVEN** a unit in review stacked on a predecessor that has gone back for rework
- **WHEN** the predecessor's branch has a commit beyond its last pushed head
- **THEN** the dependent is `planned` with the cause `upstream_went_back`, its approval, branch,
  pull request and thread are kept, and the log names the predecessor

#### Scenario: The thread knows

- **GIVEN** a dependent set back by this pass
- **WHEN** its thread is read
- **THEN** it is still at the review wait and has received the event that parked the unit, so the release resumes it as it would any parked unit

#### Scenario: A predecessor is reworked and only replies

- **GIVEN** a unit in review stacked on a predecessor that is reworking
- **WHEN** the predecessor's branch head is still its last pushed head
- **THEN** the dependent stays in review

#### Scenario: A predecessor is rebasing

- **WHEN** the predecessor is rebasing onto a moved base
- **THEN** the dependent is set back to `planned` before the new head exists

#### Scenario: A predecessor failed before editing anything

- **GIVEN** a predecessor that failed with its branch head unchanged
- **WHEN** the pass runs
- **THEN** the dependent stays in review

#### Scenario: A predecessor failed after committing

- **GIVEN** a predecessor that failed with commits beyond its last pushed head
- **WHEN** the pass runs
- **THEN** the dependent is set back to `planned`

#### Scenario: A chain

- **GIVEN** a grandchild in review on a parent in review on a grandparent whose branch is changing
- **WHEN** the pass runs
- **THEN** the parent and the grandchild are both `planned` after one pass

#### Scenario: The predecessor merges

- **WHEN** the predecessor is merged
- **THEN** the pass does not move the dependent, and the merge retargets or restacks it as before

#### Scenario: The branch is busy

- **GIVEN** a dependent whose branch claim is held by a running step
- **WHEN** the pass would move it
- **THEN** it is left for the next pass without an error

#### Scenario: The predecessor returns to review

- **GIVEN** a dependent set back by this pass
- **WHEN** the predecessor is in review again on a new head
- **THEN** the dependent is released, restacks onto that head, and keeps its approval if the restack is clean

### Requirement: What decides or counts by state asks the stored state

A check that decides what a unit may do, and a count of units by state, SHALL use the stored state, not the derived display name. The derived
names `reworking` and `rebasing` SHALL appear only where a status is shown.

#### Scenario: A chat on a unit that is reworking

- **GIVEN** a stored `running` unit that reads `reworking`
- **WHEN** a chat asks whether a step runs on it
- **THEN** it does

#### Scenario: Units counted by state

- **GIVEN** two stored `running` units, one of which reads `reworking`
- **WHEN** units are counted by state
- **THEN** the count for `running` is two
