## ADDED Requirements

### Requirement: A review comment is recorded as seen only once a unit has taken it

The poller SHALL record a pull request's new comments as seen only when the
handler of the event they raised has taken them. A comment on a pull request
whose unit is held SHALL NOT be recorded as seen. The poller SHALL report it
again on later polls, and when the unit is released the comment SHALL be
delivered as a rework with the reviewer's words. A comment on a pull request
that no unit can ever work on, such as a satisfied unit's or one with no
recorded unit, SHALL still be consumed.

#### Scenario: A comment arrives while the unit is held

- **GIVEN** an open pull request whose unit is held
- **WHEN** a reviewer leaves an inline comment and a poll runs
- **THEN** the unit is not requeued
- **AND** the comment is not recorded as seen

#### Scenario: The unit is released

- **GIVEN** a comment left while its unit was held and not recorded as seen
- **WHEN** the unit stops being held and the next poll runs
- **THEN** the unit is requeued for rework with the reviewer's comment as its
  feedback
- **AND** the comment is recorded as seen

#### Scenario: A comment on a satisfied unit

- **GIVEN** a pull request whose unit is satisfied
- **WHEN** a reviewer comments and a poll runs
- **THEN** the comment is recorded as seen and nothing is requeued
