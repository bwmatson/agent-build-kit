# commit-messages-say-why Specification

## Purpose
TBD - created by archiving change reviewers-are-told-where-to-look. Update Purpose after archive.

## Requirements

### Requirement: A build commit has a body that says why

The `test:` and `feat:` commits a unit's build makes SHALL carry, after the title, a body of one or two sentences saying why the change
exists. The body SHALL be composed by the pipeline without a model call: the first sentence of the Why section of the proposal of the
change the unit builds, then the goal ("Done when" sentence) of the groups the commit covers. The `test:` body SHALL say that the tests
come first and are expected to fail until the implementation; the `feat:` body SHALL say what holds once it lands. The pipeline's
trailers SHALL still follow the body. A change whose Why cannot be read SHALL give the goal alone, and a commit with neither SHALL be
the title alone, as before.

#### Scenario: A change with a Why and a goal

- **GIVEN** a unit of a change whose proposal Why begins "Reviewers cannot tell what matters." and whose group says "Done when the
  body opens with a Start here section."
- **WHEN** the `feat:` commit is made
- **THEN** its message is the title, a blank line, a body holding both sentences, a blank line and the `Unit:` trailer

#### Scenario: The tests commit

- **WHEN** the `test:` commit is made
- **THEN** its body says the tests come first and fail until the implementation

#### Scenario: No readable Why

- **GIVEN** a change whose proposal cannot be read
- **WHEN** a commit is made
- **THEN** its body is the goal alone

#### Scenario: Neither

- **GIVEN** a unit with no readable Why and no goal
- **WHEN** a commit is made
- **THEN** its message is the title and trailers, as before

### Requirement: A commit body is short and bounded

A commit body SHALL NOT exceed a fixed length: a longer sentence SHALL be cut at a word boundary with an ellipsis. A body SHALL NOT
contain a line that git would read as a trailer or as a comment.

#### Scenario: A long sentence

- **GIVEN** a Why whose first sentence is far over the limit
- **WHEN** the body is composed
- **THEN** it is cut at a word boundary and ends with an ellipsis

#### Scenario: A line that looks like a trailer

- **GIVEN** a goal sentence that begins "Unit: "
- **WHEN** the body is composed
- **THEN** the line is reworded so git does not read it as a trailer
