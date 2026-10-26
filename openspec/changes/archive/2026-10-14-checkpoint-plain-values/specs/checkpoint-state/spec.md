## ADDED Requirements

### Requirement: The held state is stored as plain text

When a unit is held, the state it holds SHALL be stored in the graph's checkpoint as text, and no value stored in a
checkpoint SHALL be a type that the checkpoint refuses to load. Checkpoints written earlier SHALL still load.

#### Scenario: A unit is held

- **WHEN** a node holds a unit
- **THEN** the stored held state is text and reading it back logs no blocked-type warning

#### Scenario: An earlier checkpoint

- **GIVEN** a checkpoint that holds the enum
- **WHEN** it is loaded
- **THEN** the held state reads as the same text and the unit is routed as before

### Requirement: The checkpoint test covers what nodes return

A test SHALL run the real serializer with the allowed list over every update a node returns and over a state with every
field populated, and SHALL fail if any value would be encoded as a type outside the list.

#### Scenario: A node returns an enum

- **GIVEN** a node that returns an enum member that is not on the list
- **WHEN** the test runs
- **THEN** it fails naming the node and the type

#### Scenario: Every field populated

- **WHEN** a state with every field populated is serialised
- **THEN** no value is encoded as a type outside the list
