## ADDED Requirements

### Requirement: An e2e-test result records the time of each test

The e2e-test run SHALL ask its toolchain for the duration of every test's setup, call and teardown, each its own entry, and the result posted and stored
for the unit SHALL list those entries slowest first, the number shown being a setting with every entry shown at zero. The result SHALL open its
listing with the three slowest entries. The listing SHALL sit outside the output that is cut to fit, so it is never the part dropped. A toolchain or an
output with no durations SHALL give an empty listing and no failure, and the framework outside the toolchain profiles SHALL NOT name a test runner's
flag.

#### Scenario: The durations are requested

- **GIVEN** a repo run with the python profile
- **WHEN** the e2e-test command is built
- **THEN** it asks pytest for every duration and the framework code outside the profile names no pytest flag

#### Scenario: Setup, call and teardown are separate

- **GIVEN** pytest output with a setup of 9 minutes and a call of 14 minutes for the same test
- **WHEN** the result is built
- **THEN** two entries are kept, one per phase, and the listing shows the call first

#### Scenario: The three slowest lead

- **GIVEN** a run of sixteen tests
- **WHEN** the result is posted
- **THEN** its first listing line names the three slowest entries with their phase and time

#### Scenario: The listing is cut to the configured number

- **GIVEN** the number shown is 5 and a run has 12 entries
- **WHEN** the result is posted
- **THEN** 5 are listed, the text says 5 of 12 are shown, and all 12 are recorded

#### Scenario: The listing survives a small description

- **GIVEN** a posted result whose output is cut to fit a size limit
- **WHEN** the description is built
- **THEN** the listing of durations is complete

#### Scenario: Several members

- **GIVEN** a repo with two projects whose commands each print durations
- **WHEN** the result is built
- **THEN** the entries are merged, labelled with the project, and sorted together

#### Scenario: No durations in the output

- **GIVEN** output with no durations section, or a toolchain with none
- **WHEN** the result is built
- **THEN** the listing is empty, the result is otherwise as before and nothing fails

### Requirement: A test's time is split by what it was spent on

A test suite that drives the pipeline in a scratch installation SHALL be able to report, for each phase of each e2e-test test, the time spent in agent
steps by role (with the count of calls), in the scratch pipeline's commands (checks, including their environment setup), and in everything else,
read from the ledger rows the scratch installation wrote during that phase. It SHALL print one line of a fixed prefix and JSON for each, and the e2e-test
result SHALL show the split beside the entry it belongs to and merge by test and phase. Time in neither agent nor commands SHALL be the remainder and
SHALL NOT be negative; a phase whose parts overlap SHALL say so.

#### Scenario: A phase that ran an agent step and a check

- **GIVEN** a test whose call wrote an `agent` row of 120 s for `implement` and a command span of 30 s, and took 200 s
- **WHEN** the plugin reports it
- **THEN** its line gives agent `implement` 120 s with one call, checks 30 s and other 50 s

#### Scenario: A retry is visible

- **GIVEN** a phase that wrote two `agent` rows for one role
- **WHEN** the plugin reports it
- **THEN** the role's calls are 2 and its time is their sum

#### Scenario: A fixture's time belongs to its setup

- **GIVEN** a module fixture that builds a unit in the setup of the first test that uses it
- **WHEN** the tests run
- **THEN** that time is in the first test's setup and in no other entry

#### Scenario: Parts above the wall time

- **GIVEN** a phase whose agent and check time sum above its wall time
- **WHEN** the plugin reports it
- **THEN** other is zero and the line says the parts overlap

#### Scenario: A test without a scratch ledger

- **GIVEN** an e2e-test test that does not use the scratch installation
- **WHEN** it runs
- **THEN** it has a duration entry and no split

#### Scenario: The split is shown

- **GIVEN** output with a split line for a test and phase
- **WHEN** the result is built
- **THEN** the listing shows agent, checks and other for that entry and a dash for entries without one
