## ADDED Requirements

### Requirement: The unit's log keeps the agent's words whole

A unit's run log SHALL contain the agent's replies and the commands of its tool calls in full, with a
reply's line breaks kept as indented continuation lines. The pipeline's own output SHALL keep its
one-line form. A log written before this SHALL still be read.

#### Scenario: A multi-line reply

- **WHEN** an agent replies in several paragraphs
- **THEN** the unit's log holds all of it, each continuation line indented, and the journal holds the
  one-line form

#### Scenario: A reader of the log

- **GIVEN** a log with continuation lines
- **WHEN** it is read line by line
- **THEN** every continuation line is attributed to the line that began the reply

#### Scenario: An older log

- **GIVEN** a log whose replies were clipped
- **WHEN** it is read
- **THEN** it parses and the clipped replies are shown as written
