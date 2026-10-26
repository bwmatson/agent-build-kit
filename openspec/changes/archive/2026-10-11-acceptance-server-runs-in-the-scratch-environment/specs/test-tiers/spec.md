## ADDED Requirements

### Requirement: A failed tier 2 run keeps the first error of every failed test

The tier 2 command SHALL ask its toolchain for a short failure summary of each failed or errored test, through the
toolchain profile, so that no framework code outside the profiles names a test runner's flag. The result posted and stored
for the unit SHALL list, in a part that is never cut to fit, every failed or errored test with the first failure line the
runner gave it, in the order the runner printed them, before the output that may be cut. A line SHALL be shortened only
when it exceeds a fixed length, visibly, and the full line SHALL be in the run's output file. A toolchain or an output with
no such lines SHALL give no listing and no failure.

#### Scenario: The summary is requested

- **GIVEN** a repo run with the python profile, with and without members
- **WHEN** the tier 2 command is built
- **THEN** it asks for the short failure summary and no framework code outside the profile names the flag

#### Scenario: Several tests fail on one fixture

- **GIVEN** output in which four tests of one module error with the same exception line from a module fixture
- **WHEN** the result is built
- **THEN** four entries are listed, each with its test and that line

#### Scenario: Failures and errors both listed

- **GIVEN** output with failed tests and errored tests
- **WHEN** the result is built
- **THEN** every one of them is listed with its first failure line

#### Scenario: The listing survives a small description

- **GIVEN** a run whose output is cut to fit a size limit, with thirty failed tests
- **WHEN** the description is built
- **THEN** all thirty entries are present and complete

#### Scenario: A runaway line

- **GIVEN** a failure line longer than the fixed length
- **WHEN** the result is built
- **THEN** it is shortened with a visible mark, and the output file holds it whole

#### Scenario: Nothing failed or nothing parseable

- **GIVEN** an output with no failure summary, or a toolchain with none
- **WHEN** the result is built
- **THEN** there is no listing and the result is otherwise as before

#### Scenario: The rework prompt carries the listing

- **GIVEN** a failing tier 2 result whose cut output no longer holds the first error
- **WHEN** the unit's feedback is saved
- **THEN** it holds the listing

### Requirement: The full output of a tier 2 run is kept in a file

The pipeline SHALL write the full output of every command of a unit's tier 2 run, passing commands included, to a file
under its state directory named by the unit and the time, appended after each command so a run that is stopped leaves
what it had. The result text SHALL name the file's path in the part that is never cut to fit, the unit's run log SHALL
name it, and `abk status` SHALL show it for a unit whose last result was a tier 2 failure. The files SHALL be kept
machine-local, SHALL be limited in number per unit as run logs are, and SHALL be removed when their change is archived. The
file and the result text SHALL be redacted by the function that replaces known secret values before they are written, and
a redaction that fails SHALL withhold the text and say so.

#### Scenario: The whole output is kept

- **GIVEN** a tier 2 run whose output is far longer than the cut kept in the result
- **WHEN** it ends
- **THEN** the file holds every command's output whole, and the result names its path

#### Scenario: A stopped run leaves what it had

- **GIVEN** a run of two commands in which the second raises
- **WHEN** the run ends
- **THEN** the file holds the first command's output

#### Scenario: The named file

- **GIVEN** a unit `change/2` run at a given time
- **WHEN** the file is written
- **THEN** its name holds the change, the unit's number and the time, and a change whose name begins with the same letters is not matched

#### Scenario: The file is found

- **WHEN** a unit's run log and `abk status` for a unit whose last result was a tier 2 failure are read
- **THEN** each names the file's path

#### Scenario: Old files are removed

- **GIVEN** more runs of a unit than the bound allows, and an archived change
- **WHEN** a run is written and the change is archived
- **THEN** only the most recent files of the unit remain, and the archived change's are removed

#### Scenario: A secret in the output

- **GIVEN** an output that holds a known secret value
- **WHEN** the file and the result are written
- **THEN** both hold `[redacted:<NAME>]` in its place and the value appears in neither

#### Scenario: A redaction that fails

- **GIVEN** a redaction that raises
- **WHEN** the file and the result are written
- **THEN** the file holds the withheld notice, the result says the output is withheld, and the run's own result is unchanged

#### Scenario: The dev stack path

- **GIVEN** a repo that runs tier 2 through its own dev stack script
- **WHEN** the run ends
- **THEN** the script's output is in a file and named in the result as for any other run
