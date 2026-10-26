## ADDED Requirements

### Requirement: Reviews made in the web UI are a comment source

The poller SHALL read reviews made in the web UI for a unit as comments, replies and a decision on its
pull request, with identifiers that cannot collide with the host's, and SHALL write the agent's
replies back to the thread they answer.

#### Scenario: A comment from the UI

- **WHEN** a reviewer comments in the UI on a unit with a pull request
- **THEN** the next poll sees one new comment and sends the unit back for rework

#### Scenario: A reply from the agent

- **GIVEN** a rework that answers a UI comment
- **WHEN** the replies are posted
- **THEN** each appears in the thread it answers and is not seen again as a new comment
