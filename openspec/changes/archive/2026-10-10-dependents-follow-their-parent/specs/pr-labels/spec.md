## ADDED Requirements

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
