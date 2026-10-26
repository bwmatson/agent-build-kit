## RENAMED Requirements

- FROM: `### Requirement: The overlay is read by every consumer of the configuration and written by none`
- TO: `### Requirement: The overlay is read by every consumer of the configuration and written only by the migration`

## MODIFIED Requirements

### Requirement: The overlay is read by every consumer of the configuration and written only by the migration

The merged configuration SHALL be the one `Installation` exposes, so verification, redaction and scrub terms read overlay values without
a special case. `abk init`, `abk policy apply` and `abk project init` SHALL edit only the abk.yaml in force and SHALL NOT create or modify
`abk.local.yaml`. The one command that writes it is `abk config --migrate`, which moves the machine settings of a tracked abk.yaml into it
(spec `config-migration`) and writes nothing else to it. `abk config` SHALL print the merged configuration and name on the error stream the top-level keys the local file set,
and `abk config --path` SHALL print both paths when the overlay exists.

#### Scenario: An overlay provider is resolved and redacted

- **GIVEN** a `verify.env` entry with an `env-file` provider only in the local file
- **WHEN** verification resolves its environment and a stored text contains the value
- **THEN** the variable is given to the tests and the stored text holds the redaction marker

#### Scenario: A writer leaves the overlay alone

- **GIVEN** an existing `abk.local.yaml`
- **WHEN** `abk project init` registers a project
- **THEN** the entry is added to `abk.yaml` and the overlay's bytes are unchanged

#### Scenario: Config shows what the overlay set

- **GIVEN** an overlay setting `verify` and `repos`
- **WHEN** `abk config` runs
- **THEN** the merged document is printed and the error stream says the local file set `verify` and `repos`

#### Scenario: The migration writes the overlay and nothing else of it

- **GIVEN** an existing `abk.local.yaml` with a comment and a `verify` block, and a tracked abk.yaml with a repo path to move
- **WHEN** `abk config --migrate --yes` runs
- **THEN** the path is added to the overlay and every other byte of it, comment and `verify` block included, is unchanged
