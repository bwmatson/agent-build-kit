## ADDED Requirements

### Requirement: `abk tags` says what to pass when it is given nothing

`abk tags` SHALL require either a change name or `--all`. With neither, or with both, it SHALL print one line to
standard error saying what to pass, exit with status 2 and read no change; it SHALL NOT fail with a traceback. Given a
change name alone, or `--all` alone, it SHALL behave as it did before.

#### Scenario: Neither a change nor `--all`

- **WHEN** `abk tags` is run with no argument
- **THEN** it prints `name a change, or pass --all for every change` to standard error, exits 2 and shows no traceback

#### Scenario: Both a change and `--all`

- **WHEN** `abk tags` is run with a change name and `--all`
- **THEN** it refuses with one line on standard error, exits 2 and checks no change

#### Scenario: A change or `--all` alone

- **WHEN** `abk tags` is run with a change name, or with `--all`
- **THEN** it validates that change, or every change, and reports as before

#### Scenario: The help names the flag

- **WHEN** `abk tags --help` is run
- **THEN** the text names `--all`
