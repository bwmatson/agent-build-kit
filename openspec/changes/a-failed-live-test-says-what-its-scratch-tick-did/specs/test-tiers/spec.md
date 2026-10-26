## ADDED Requirements

### Requirement: Live tests that start a tick share one helper and a guarded check of the unit's branch

A live test that starts `abk tick` in a scratch installation SHALL run it through one shared helper, not through a result type and tick function of its
own. The helper SHALL return the return code, the output lines with the time each arrived, and a summary of the scratch environment that lists
the names of environment variables and the values of those whose names do not look secret, redacted, and SHALL remember the last three ticks of
each scratch. A live test SHALL read a unit's branch on the remote through one shared check, which SHALL fail, and not raise a git error, when the
branch is missing, and whose failure SHALL open with a line of cause hints and then give the tick's return code and output, the unit's wait
reasons, the tail of the run log, the pause marker and who pushed. An assertion in a live test about a tick or a unit's state SHALL carry the
tick's output in its message.

#### Scenario: The branch never arrived

- **GIVEN** a tick that built nothing and printed `nothing ready to build`
- **WHEN** the test reads the unit's branch through the check
- **THEN** it fails with a first line `cause hints:` and the tick's whole output, not a `CalledProcessError`

#### Scenario: The branch exists

- **GIVEN** a remote with the unit's branch of two commits
- **WHEN** the check runs
- **THEN** it returns the two commit ids

#### Scenario: A source of the failure cannot be read

- **GIVEN** a missing branch and an unreadable pause marker
- **WHEN** the check fails
- **THEN** the failure says the marker could not be read and still holds the tick's output

#### Scenario: No file defines its own tick

- **WHEN** the live test files are scanned
- **THEN** none defines its own tick result type, runs `abk tick` itself or runs `git log` of the unit's branch outside the helper

### Requirement: A failed live test prints the state of its scratch installation

When a test marked as needing the live stack fails or errors in any phase and has a scratch installation, its output SHALL end with a section named
`SCRATCH STATE` that opens with a line of cause hints and holds: the output of the last tick, each unit's latest wait reason, a summary of the stored
units (id, state, branch, held by, failure reason), the pause marker or `absent`, the lease and lock holders, the heads of the remote and the
branches of the code repository, the tails of the decision log and the usage ledger, the requests the fake host recorded, and the tick environment as
names with non-secret values. Each item SHALL have its own cap, one test's section SHALL be at most 20 480 characters and one session's sections at
most 61 440, after which a failing test gets one line saying its section was left out. The text SHALL be redacted before it is printed, and if
redaction fails it SHALL be withheld with a line saying so. Building it SHALL be best effort: a source that cannot be read SHALL be named in one
line, and nothing it does SHALL change the test's outcome, run the pipeline, take a lock or write in the scratch installation. Nothing SHALL be
kept in any other place, and no setting SHALL govern its retention.

#### Scenario: A test fails after a tick built nothing

- **GIVEN** a failed live test whose tick printed `nothing ready to build` and left a usage pause marker
- **WHEN** its output is read
- **THEN** the `SCRATCH STATE` section opens with cause hints naming the pause, and holds the tick's output, the unit's reason and the marker

#### Scenario: A test that passes or has no scratch

- **GIVEN** a passing live test, a skipped one, a failing test that is not a live one, and a failing live test with no scratch installation
- **WHEN** their outputs are read
- **THEN** none has a `SCRATCH STATE` section

#### Scenario: An error in setup or teardown

- **GIVEN** a live test that errors in its setup after its scratch was made
- **WHEN** its output is read
- **THEN** the section is there

#### Scenario: The caps

- **GIVEN** a tick output of 100 000 characters, forty units and a hundred branches
- **WHEN** a test fails
- **THEN** the tick output is cut to its last 6000 characters, twenty units are listed, thirty branches are listed and the section is at most 20 480 characters

#### Scenario: A third dump over the session cap

- **GIVEN** two dumps that used 61 440 characters between them
- **WHEN** a third live test fails
- **THEN** its output has one line saying its section was left out

#### Scenario: A secret in the state

- **GIVEN** an environment variable named like a secret whose value also appears in the tick output and in a unit's failure reason
- **WHEN** a test fails
- **THEN** the value appears nowhere in the section and the variable's name does

#### Scenario: Redaction fails

- **GIVEN** the redactor raises
- **WHEN** a test fails
- **THEN** the section is one line saying it was withheld because redaction failed

#### Scenario: The dump itself fails

- **GIVEN** a stored-units file that cannot be read
- **WHEN** a test fails
- **THEN** the section says that item is unavailable with the error's type, still holds the other items, and the test's traceback and outcome are those it would have without the plugin

#### Scenario: The hook leaves the scratch alone

- **WHEN** a section is built
- **THEN** no file in the scratch installation is created or changed, no tick is run and no lock is taken
