## ADDED Requirements

### Requirement: The Claude Code runtime defaults to sonnet for building and opus for review

The Claude Code runtime's default models SHALL be `sonnet` for implementing, `sonnet` for reworking, `opus` for reviewing a
fresh build and `opus` for reviewing a rework. A role the configuration names SHALL keep the name it gives, and a role it
does not name SHALL take the default. A runtime that declares no model names SHALL be unaffected.

#### Scenario: No models configured

- **GIVEN** a configuration with no models block on the Claude Code runtime
- **WHEN** the models are resolved
- **THEN** implementing and reworking are `sonnet` and both reviews are `opus`

#### Scenario: Some roles named

- **GIVEN** a flat models block that names only `implement`
- **WHEN** the models are resolved
- **THEN** that role keeps its name and the others take the new defaults

#### Scenario: A model override

- **GIVEN** a per-machine override for the review model
- **WHEN** the models are resolved
- **THEN** the override wins over the default

#### Scenario: A runtime with no names

- **GIVEN** a runtime that declares no model names
- **WHEN** the models are resolved
- **THEN** every role is empty and runs on the agent's own default

### Requirement: The documents state the defaults and why the reviews differ from the author

The documents that state the default models SHALL state the new ones, SHALL say that building and reworking default to a
model different from the one that reviews them, and SHALL say to set the reviewer of reworks to a model different from the
author's when the author is set to the reviewer's model.

#### Scenario: The configuration reference

- **WHEN** the reference's models block is read
- **THEN** it shows the four new defaults and the reason the reviews are not the author's model
