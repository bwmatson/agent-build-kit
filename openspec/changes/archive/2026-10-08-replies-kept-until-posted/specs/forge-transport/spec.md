## ADDED Requirements

### Requirement: An owed reply is kept until it is posted

A reply or comment the pipeline owes a pull request SHALL stay pending until it has been posted or
found already posted, and SHALL be attempted again on a later pass when it could not be posted. A
reply SHALL NOT be posted twice.

#### Scenario: A reply fails once

- **GIVEN** a reply that the host refuses on every attempt of one pass
- **WHEN** the next pass runs and the host answers
- **THEN** the reply is posted once and removed from the pending list

#### Scenario: A reply that landed

- **GIVEN** a reply the host stored although its answer was lost
- **WHEN** the pass attempts it again
- **THEN** it is recognised as posted and not posted again

### Requirement: A satisfied unit's pull request is closed

A satisfied unit's pull request SHALL be closed by posting the reason and closing it, repeated on
later passes until both are done, without posting the reason twice.

#### Scenario: The host fails after the reason is posted

- **GIVEN** a reason posted and a close that failed
- **WHEN** the next pass runs
- **THEN** the pull request is closed and the reason is not posted again
