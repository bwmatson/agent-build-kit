# stored-text-scrub Specification

## Purpose
TBD - created by archiving change planning-content-follows-the-public-rule. Update Purpose after archive.

## Requirements

### Requirement: The store rewrites text fields through one exclusive method

`UnitStore` SHALL offer a method that applies a function to the text fields of every record (`feedback`, `guidance`,
`predecessor_note`, `stack_refusal`, the `note` of each history entry) under the store's lock, writes the result once through the store's
own writer, and returns the ids it changed. It SHALL change no field other than those, no timestamp and no state, and SHALL write nothing
when no text changed.

#### Scenario: Only text fields change

- **GIVEN** a record with a home path in its feedback and in a history note
- **WHEN** the method is applied with a function replacing the path
- **THEN** both are replaced and every other field is equal to what it was

#### Scenario: Nothing to change

- **GIVEN** records with no match
- **WHEN** the method runs
- **THEN** the file's bytes and modification time are unchanged and the list is empty

#### Scenario: One write under the lock

- **GIVEN** two records with matches
- **WHEN** the method runs while another writer waits
- **THEN** the file is written once and the other writer sees both changes

### Requirement: `abk scrub-store` replaces home-directory paths in stored text

`abk scrub-store` SHALL, by default, print for each record and field the number of home-directory paths it holds (never the text) and
change nothing. With `--apply` it SHALL refuse unless the pipeline is paused, SHALL keep the original as `<store>.pre-redact` (an
existing copy kept, not overwritten), SHALL replace each path's home prefix (the Linux and macOS home roots and user directory, and a tilde-slash prefix followed by a
directory the tool allowance does not name) with `<home>/` through the store method, and SHALL leave every other term in the text. A second
run SHALL find nothing and write nothing.

#### Scenario: Dry run

- **GIVEN** a record whose feedback holds a home path
- **WHEN** `abk scrub-store` runs
- **THEN** it prints the record, the field and the count, the text is not printed, and the file is unchanged

#### Scenario: Apply

- **GIVEN** the same record and a paused pipeline
- **WHEN** `abk scrub-store --apply` runs
- **THEN** the feedback holds `<home>/` where the prefix was, the rest of the path is kept, and a `.pre-redact` copy holds the original

#### Scenario: Refused while running

- **GIVEN** a pipeline that is not paused
- **WHEN** `abk scrub-store --apply` runs
- **THEN** it exits 1, says to pause the pipeline, and changes nothing

#### Scenario: Second run

- **GIVEN** a store already scrubbed
- **WHEN** `abk scrub-store --apply` runs again
- **THEN** it reports nothing found, writes nothing, and the first `.pre-redact` copy is unchanged

#### Scenario: A repo name in feedback stays

- **GIVEN** feedback naming a repo and a home path
- **WHEN** the scrub is applied
- **THEN** the repo name is unchanged

### Requirement: Redaction copies are ignored wherever the state directory is

The packaged ignore list SHALL ignore `*.pre-redact` at any depth, replacing the line tied to the default state directory, and the scrub
pass and `abk redact-history` SHALL both write the copy with that suffix.

#### Scenario: The template

- **GIVEN** the packaged ignore template
- **WHEN** it is read
- **THEN** it holds `*.pre-redact` and no `runs/**/*.pre-redact`

#### Scenario: A moved state directory

- **GIVEN** `planning.state_dir` set to another directory and a copy written there
- **WHEN** git is asked whether it is ignored
- **THEN** it is ignored

### Requirement: Issue and pull-request references are scrubbed with the home paths

`abk scrub-store` SHALL also find, count and replace issue and pull-request references in the stored text fields (a repository name, a hash sign and a number, such as `example/app#15`), replacing each with `<ref>`; the dry run SHALL count them beside the home paths without printing the text, and a second `--apply` SHALL find nothing. The text pass of `abk planning split --scrub` SHALL replace them too. The pattern SHALL be defined once and shared with the structural leak test.

#### Scenario: A note with a reference

- **GIVEN** a record whose history note holds `<redacted>/app#15 can't be closed`
- **WHEN** `abk scrub-store --apply` runs on a paused pipeline
- **THEN** the note reads `<redacted>/<ref> can't be closed`, no other field changes, and a second run writes nothing

#### Scenario: A split scrubs a reference

- **GIVEN** a moved record whose feedback holds `example/app#15`
- **WHEN** the split runs with `--scrub`
- **THEN** the moved record holds `<ref>` and the dry run counts it among the substitutions
