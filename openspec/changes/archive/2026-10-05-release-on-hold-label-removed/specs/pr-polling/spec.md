## ADDED Requirements

### Requirement: Removing the hold label releases the unit it held

The poller SHALL report the `agent-hold` label leaving a pull request, and the
runner SHALL return a unit held by that label to waiting for review, without a
person requeuing it. A unit that is held for another reason (the review loop's
own hold, a stack depth cap, a toolchain the pipeline cannot build) SHALL stay
held, and the log SHALL say why. Whatever happened on the pull request during the
hold SHALL be delivered afterwards by the usual events. A release that arrives
while the unit is being built SHALL be deferred, not lost.

#### Scenario: A person removes the label

- **GIVEN** a unit held because `agent-hold` was added to its pull request
- **WHEN** the label is removed and a poll runs
- **THEN** the unit returns to waiting for review
- **AND** the pipeline's state label on the pull request is `in-review` again

#### Scenario: A hold the label did not cause

- **GIVEN** a unit the review loop held, whose pull request also had the label
  added and removed
- **WHEN** the removal is polled
- **THEN** the unit stays held and the log says the hold was not the label's

#### Scenario: A comment left during the hold

- **GIVEN** a comment added while the unit was held
- **WHEN** the unit is released
- **THEN** the next poll delivers the comment as a rework

#### Scenario: The unit is being built

- **GIVEN** a unit being built when the label is removed
- **WHEN** the poll runs
- **THEN** the release is deferred and reported again on a later poll
