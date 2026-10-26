## ADDED Requirements

### Requirement: No document says a human merges every pull request

The README, `AGENTS.md`, `docs/architecture.md`, `docs/configuration.md`, `docs/cli.md`, `docs/code-forges.md`,
`docs/unit-graph.md`, the three skills as shipped and their mirror in the repository's own `.claude/skills`, the footer of a pull
request body and the message of the command policy SHALL NOT state that a human, or a person, merges every pull request or that the
pipeline never merges. Where they say who merges they SHALL say that a person merges every pull request that was not auto-landed and
that the build agent never merges. The shipped skills and their mirror SHALL hold the same text.

#### Scenario: The pull request footer

- **WHEN** a pull request body is built
- **THEN** the footer says the build agent never merges and that the pipeline merges only a unit review classified `auto` and policy allowed, and does not say a human merges every one

#### Scenario: The command policy's refusal

- **GIVEN** a merge command offered to the policy
- **WHEN** it is refused
- **THEN** the message says the agent never merges and does not say who does

#### Scenario: The README and AGENTS.md

- **WHEN** their text is read
- **THEN** each says a person merges what was not auto-landed

### Requirement: A test fails when a document states the old rule

A test SHALL read every Markdown file of the repository, the shipped skills and the strings the pull request footer and the command
policy produce, and SHALL fail, naming file and line, on a statement that a human or a person merges every pull request, with the
changelog and the two documents that record the decision exempt by name. It SHALL also fail when a shipped skill and its mirror
differ.

#### Scenario: A stray statement

- **GIVEN** a document that says "a human merges every PR"
- **WHEN** the test runs
- **THEN** it fails naming the file and line

#### Scenario: A drifted mirror

- **GIVEN** a mirror skill that differs from the shipped one
- **WHEN** the test runs
- **THEN** it fails naming the skill

#### Scenario: The repository

- **WHEN** the test runs over the repository
- **THEN** it passes

### Requirement: The documents describe the removed and what stays

The documents SHALL describe the review reply as carrying a classification beside `needs_human` and `escalate`, which a reviewer
uses to hand a problem it cannot resolve to a person before a pull request is opened, review by tier as always on,
and `review.ceilings` as the only ceilings, and SHALL NOT mention `review.enabled` or `max_unit_lines` except in the changelog and in
the message that names the migration. `docs/agent-efficient-coding-philosophy.md` and `docs/risk-tiered-review-design.md` SHALL each
carry a note that its design is implemented. The changelog SHALL have one entry for each user-visible change of this work.

#### Scenario: The status note

- **WHEN** the philosophy and the design document are read
- **THEN** each opens with a note that its status is implemented

#### Scenario: The removed names

- **WHEN** the documents other than the changelog are searched for `review.enabled` and `max_unit_lines`
- **THEN** none is found outside the migration message

#### Scenario: The changelog

- **WHEN** the unreleased section is read
- **THEN** it has an entry for each of: the removal of `review.enabled`, the removal of `max_unit_lines`, and the wording of who merges
