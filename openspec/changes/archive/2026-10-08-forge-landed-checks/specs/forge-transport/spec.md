## ADDED Requirements

### Requirement: A lookup distinguishes none from unknown

A forge's pull request lookup SHALL return nothing only when the host answered that there is no
pull request, and SHALL raise when it could not tell. A create refused because the pull request
already exists SHALL return that pull request.

#### Scenario: The host is down during a lookup

- **GIVEN** a host that cannot be reached
- **WHEN** the pipeline looks for a pull request by its head
- **THEN** the lookup raises and does not report that none exists

#### Scenario: A duplicate create

- **GIVEN** a pull request that already exists for a head and base
- **WHEN** a create is refused as a duplicate
- **THEN** the existing pull request is returned

### Requirement: A forge can say whether a comment already exists

Each forge SHALL answer whether a comment carrying the pipeline's marker and a given body exists
on a pull request, or as a reply to a given comment, and return its identifier when it does.

#### Scenario: A comment that landed

- **GIVEN** a reply the host stored although its answer was lost
- **WHEN** the existence of that reply is asked
- **THEN** its identifier is returned

#### Scenario: No such comment

- **WHEN** no comment matches
- **THEN** nothing is returned

### Requirement: A failed follow-up to a create does not fail the unit

After a pull request exists, a failure to update its body or to post its status SHALL be logged and
counted and SHALL NOT fail the unit, on every host.

#### Scenario: A status post fails after the create

- **GIVEN** a pull request just created
- **WHEN** posting its status fails
- **THEN** the unit continues to review
