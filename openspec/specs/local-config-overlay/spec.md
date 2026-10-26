# local-config-overlay Specification

## Purpose
TBD - created by archiving change planning-content-follows-the-public-rule. Update Purpose after archive.

## Requirements

### Requirement: `abk.local.yaml` is merged over `abk.yaml` at load

When a file named `abk.local.yaml` sits beside the abk.yaml in force, the loader SHALL parse both, merge them, and validate the result
with the same strict schema as before. Two mappings SHALL merge key by key, recursively; any other value in the local file (a scalar, a
list, a string, `null`) SHALL replace the committed one whole; a key only in the local file SHALL be added. A missing local file SHALL
change nothing. A local file that is unreadable, not valid YAML or not a mapping SHALL be a configuration error naming it.

#### Scenario: A mapping merges

- **GIVEN** `verify.env` holding `A` in `abk.yaml` and `B` in `abk.local.yaml`
- **WHEN** the configuration loads
- **THEN** `verify.env` holds both

#### Scenario: A list is replaced

- **GIVEN** `deploy.live_written` of two paths in `abk.yaml` and one in the local file
- **WHEN** the configuration loads
- **THEN** it holds the one

#### Scenario: A prose string is replaced

- **GIVEN** `relationships` of a repo in both files
- **WHEN** the configuration loads
- **THEN** the local text is the value

#### Scenario: Null switches a setting off

- **GIVEN** a committed setting and a local `null` for it
- **WHEN** the configuration loads
- **THEN** the value is `null`

#### Scenario: No local file

- **GIVEN** no `abk.local.yaml`
- **WHEN** the configuration loads
- **THEN** it equals what loading `abk.yaml` alone gives

#### Scenario: A broken local file

- **GIVEN** an `abk.local.yaml` holding a list at the top level
- **WHEN** the configuration loads
- **THEN** the error names `abk.local.yaml` and says a mapping is required

### Requirement: A schema error names the file the key came from

The strict schema SHALL still refuse an unknown key in the merged document, and the error SHALL name `abk.local.yaml` when the failing key
path is present in the local mapping and `abk.yaml` otherwise.

#### Scenario: An unknown key in the local file

- **GIVEN** a misspelled key under `repos.app` in `abk.local.yaml`
- **WHEN** the configuration loads
- **THEN** the error names `abk.local.yaml` and the key path

#### Scenario: An unknown key in the committed file

- **GIVEN** the same misspelling in `abk.yaml`
- **WHEN** the configuration loads
- **THEN** the error names `abk.yaml`

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

### Requirement: `abk init` ignores the overlay and says where installation facts go

`abk init` SHALL add `abk.local.yaml` and `scrub.local` to the planning repo's ignore file (the packaged template for a new one, a line
appended once to an existing one), SHALL name `abk.local.yaml` in `.env.example`'s header note, and SHALL say in the planning context template and in
its closing output what the file is for: structured, user-specific configuration merged over `abk.yaml` (a second variant of a section, a
per-user list), where single values that one would write in `abk.yaml` but not commit go in `.env` instead.

#### Scenario: A new planning repo

- **GIVEN** an empty directory
- **WHEN** `abk init` runs
- **THEN** the ignore file lists `abk.local.yaml`, `scrub.local` and `*.pre-redact`

#### Scenario: An existing ignore file

- **GIVEN** an ignore file already holding `abk.local.yaml`
- **WHEN** `abk init` runs again
- **THEN** the line appears once

#### Scenario: Idempotent

- **GIVEN** an installation initialised twice
- **WHEN** the files are compared
- **THEN** the second run changed none of them
