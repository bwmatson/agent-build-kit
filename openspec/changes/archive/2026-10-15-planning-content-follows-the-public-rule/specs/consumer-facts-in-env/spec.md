## ADDED Requirements

### Requirement: `abk init` ignores the local list and says where a consumer's facts go

`abk init` SHALL add `scrub.local` and `*.pre-redact` to the planning repo's ignore file (the packaged template for a new one, a line
appended once to an existing one), SHALL name `scrub.local` in `.env.example`'s header note, and SHALL say in the planning context
template and in its closing output that a consumer's stack facts (an agent command, local ports, a home variable and path) belong in the
ignored `.env` and are read by `from: env-file` entries of `verify.env`, and that a planning repo that plans only itself needs no other
repo entries. It SHALL create neither file.

#### Scenario: A new planning repo

- **GIVEN** an empty directory
- **WHEN** `abk init` runs
- **THEN** the ignore file lists `scrub.local` and `*.pre-redact`, and no other file for installation facts is created

#### Scenario: An existing ignore file

- **GIVEN** an ignore file already holding `scrub.local`
- **WHEN** `abk init` runs again
- **THEN** the line appears once and `*.pre-redact` is added once

#### Scenario: The guidance is printed

- **GIVEN** a new planning repo
- **WHEN** `abk init` finishes
- **THEN** its output and the generated planning context say consumer facts go in `.env` through `from: env-file`

### Requirement: Consumer facts of a tracked abk.yaml live in `.env`

The documentation and the packaged `abk-config` skill SHALL say that the one way to keep a consumer's facts out of a tracked `abk.yaml` is
to keep each value in the ignored `.env` and name it in `verify.env` with `from: env-file`, `file: .env` and `key: <NAME>`, with a worked
example using generic names, and that a planning repo that plans only itself needs no other repo entries in its `abk.yaml`.

#### Scenario: A worked example

- **GIVEN** the packaged skill and the configuration guide
- **WHEN** they are read
- **THEN** each shows a `verify.env` entry with `from: env-file`, `file: .env` and a generic key name
