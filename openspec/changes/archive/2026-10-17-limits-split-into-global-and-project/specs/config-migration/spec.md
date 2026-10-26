## ADDED Requirements

### Requirement: `abk config --migrate` moves an abk.yaml to the new limits blocks by text

`abk config --migrate` SHALL rewrite the abk.yaml in force so that a root `limits` key becomes `global_limits` and the settings
`max_units_in_progress`, `max_concurrent_stacks` and `max_concurrent_restacks` found under it (or already under `global_limits`)
are moved into a `project_limits` block placed straight after the `global_limits` block, each with its value, the comment at
the end of its line, and the comment lines directly above it. It SHALL write by editing the file's original text, never by writing
the parsed document out again: every other byte of the file (comments, spellings of values, spacing, key order, line breaks,
indentation, document markers, a missing final newline) SHALL be unchanged. When `global_limits` would be left with no setting it
SHALL be written as `global_limits: {}`. The key and the indentation of the moved lines SHALL follow the file's own style.
Before it writes it SHALL check that the new text parses and holds exactly the old document with those keys renamed and moved,
and it SHALL write nothing when that is not so.

#### Scenario: The old block is renamed and the three are moved

- **GIVEN** a file with `limits:` holding `max_review_rounds`, `max_units_in_progress`, `max_concurrent_stacks` and `max_concurrent_restacks`
- **WHEN** it is migrated
- **THEN** `limits:` reads `global_limits:` holding only `max_review_rounds`, and a `project_limits:` block follows it holding the other three with their values and comments

#### Scenario: Every other byte is unchanged

- **GIVEN** a file with comments, quoted values, `~` and `null`, extra spaces before a value or a comment, mixed indentation, CRLF line endings, a leading `---` and no final newline
- **WHEN** it is migrated
- **THEN** the diff of before and after holds only the renamed key line, the removed lines of the three settings and the added `project_limits` lines, and every other line is byte for byte as it was

#### Scenario: A block left empty

- **GIVEN** a `limits` block holding only the three settings
- **WHEN** it is migrated
- **THEN** it reads `global_limits: {}` and the three are under `project_limits`, and the file loads

#### Scenario: A file already on the new names with one left behind

- **GIVEN** a `global_limits` block that still holds `max_units_in_progress`
- **WHEN** it is migrated
- **THEN** only that setting moves to `project_limits`, and `global_limits` keeps its name

#### Scenario: Comments move with their setting

- **GIVEN** a comment line directly above `max_concurrent_stacks` and a comment at the end of its line
- **WHEN** it is migrated
- **THEN** both are in `project_limits` with the setting, and a comment above a setting that stays remains where it was

#### Scenario: The result loads

- **WHEN** a migrated file is loaded
- **THEN** it loads with no deprecation notice and the same limits it meant before

### Requirement: A migration refuses what it cannot edit safely and writes nothing

`abk config --migrate` SHALL refuse, naming the file and the key and saying why, exiting 2 and writing nothing (no backup and no
temporary file), when the file does not parse, has several documents, holds a `limits` and a `global_limits` together, writes the
block in flow style or as a single value, writes a moved setting with a value on more than one line, gives a moved key with an
anchor or a merge key, or already holds the same setting in `project_limits`.

#### Scenario: A block in flow style

- **GIVEN** `limits: {max_units_in_progress: 5}`
- **WHEN** it is migrated
- **THEN** it refuses naming `limits` and says a flow-style block cannot be edited without rewriting the line, and the file is unchanged

#### Scenario: Both old and new keys

- **GIVEN** a file with `limits` and `global_limits`
- **WHEN** it is migrated
- **THEN** it refuses naming both keys, and the file is unchanged

#### Scenario: The setting is already in `project_limits`

- **GIVEN** `project_limits: {max_units_in_progress: 3}` and `limits: {max_units_in_progress: 5}`
- **WHEN** it is migrated
- **THEN** it refuses naming the setting, and the file is unchanged

#### Scenario: A file that does not parse

- **WHEN** the file is not valid YAML
- **THEN** it refuses, naming the file, and writes nothing

### Requirement: A migration keeps one backup, asks, and is idempotent

The first time `abk config --migrate` writes a file it SHALL copy the original to `<file>.abk-backup` beside it and SHALL never
overwrite that copy. It SHALL write through a temporary file in the file's directory, keeping the file's mode, and replace the
file in one step. It SHALL print a diff of the change and ask before writing, unless `--yes` is given; `--dry-run` SHALL print the
diff and write nothing; a person who declines, and a run with no terminal to ask on and no `--yes`, SHALL write nothing and exit 1. It SHALL exit 0
when it wrote and when nothing needed migrating. Run again on a migrated file it SHALL say nothing needed migrating, write
nothing and make no second backup.

#### Scenario: A yes writes

- **WHEN** the person confirms
- **THEN** the diff is printed first, the file is written, the backup's path is printed, and the exit status is 0

#### Scenario: `--yes` does not ask

- **WHEN** `abk config --migrate --yes` runs
- **THEN** it prints the diff, asks nothing and writes

#### Scenario: A no, or no terminal

- **WHEN** the person declines, or the command runs with no terminal and no `--yes`
- **THEN** no file, backup or temporary file is written and the exit status is 1

#### Scenario: A dry run

- **WHEN** `abk config --migrate --dry-run` runs
- **THEN** the diff is printed, nothing is written and the exit status is 0

#### Scenario: A second run

- **GIVEN** a file that was migrated
- **WHEN** the command runs again
- **THEN** it says nothing needed migrating, asks nothing, writes nothing, makes no second backup and exits 0

#### Scenario: The backup is kept once

- **GIVEN** a backup from an earlier migration of the same path
- **WHEN** a later migration writes
- **THEN** the backup still holds the first original

#### Scenario: A file that does not load for a moved setting

- **GIVEN** a file whose `global_limits` holds a moved setting, so it does not load
- **WHEN** `abk config --migrate` runs
- **THEN** it migrates it, because the command does not load the configuration first, and with `--config` it migrates the named file
