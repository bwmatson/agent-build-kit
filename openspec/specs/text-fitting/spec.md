# text-fitting Specification

## Purpose
TBD - created by archiving change fit-to-budget. Update Purpose after archive.

## Requirements

### Requirement: Text is cut by one set of cuts

The pipeline SHALL cut text through shared functions that keep the head, the tail or both, on a character, line or paragraph
boundary, that return the text unchanged when it fits, never return more than the size asked, and close any code fence or
collapsible block they leave open.

#### Scenario: A text that fits

- **WHEN** a text within the size is cut
- **THEN** it is returned unchanged

#### Scenario: A cut inside a code fence

- **WHEN** a cut leaves a code fence open
- **THEN** the fence is closed within the size asked

### Requirement: A budget is shared between sections, and unused allocation is passed on

The fitter SHALL render every section in full when they fit, and otherwise SHALL give each section its smallest honest form,
share the rest by weight, and give a section that needs less than its share only what it needs, passing the remainder to the
other sections until no section is newly satisfied. Required sections SHALL never be reduced below their smallest form or
dropped, and the result SHALL NOT exceed the budget.

#### Scenario: A short section gives room to a long one

- **GIVEN** two sections of equal weight, one that needs a tenth of its share and one that needs more than its share
- **WHEN** the budget is shared
- **THEN** the second receives its share plus the unused part of the first

#### Scenario: Everything fits

- **WHEN** the sections together fit the budget
- **THEN** all are rendered in full

#### Scenario: Weights

- **GIVEN** two sections that both need more than their share, one of weight two and one of weight one
- **WHEN** the budget is shared
- **THEN** the first receives twice what the second does above their smallest forms

#### Scenario: Not enough for every smallest form

- **GIVEN** a budget smaller than the smallest forms together
- **WHEN** the budget is shared
- **THEN** sections are dropped from the lowest weight, required sections are kept, and the result does not exceed the budget

#### Scenario: Determinism

- **WHEN** the same sections and budget are fitted twice
- **THEN** the result is identical

### Requirement: The limit is the lowest any host allows and the fit is made once

Each host SHALL declare its description limit and its status description limit, the base of the forge layer SHALL work out
the effective limit as the lowest across the registered hosts, and a description SHALL be fitted to it once, where it is handed
to a forge. The code of a host SHALL NOT cut descriptions.

#### Scenario: The same description on every host

- **GIVEN** a unit and the same inputs for two hosts that declare different limits
- **WHEN** the description is built
- **THEN** it is the same text for both, fitted to the lower limit

#### Scenario: A host with a lower limit is added

- **WHEN** a host is registered that declares a lower limit
- **THEN** the effective limit becomes that one

#### Scenario: A status description

- **WHEN** a status description is built
- **THEN** it is fitted to the lowest status limit across the hosts, and no host cuts it again

#### Scenario: A host declares its status limit

- **WHEN** a host is registered
- **THEN** it declares a status description limit as well as a description limit

### Requirement: The pull request description keeps what it kept

The description SHALL be built from sections that use the fitter, with the position, scope, assumptions, held points and
footer required, the test output of weight one with a smallest form that keeps the pass or fail line, and the follow-ups of
weight two with a smallest form that counts those left out. A description that fits SHALL be unchanged, the tail of the
output SHALL be kept and its head dropped, follow-ups SHALL be whole items in order followed by a count, and the verdict and
the headings SHALL survive.

#### Scenario: No follow-ups

- **GIVEN** a description with no follow-ups that is over the limit
- **WHEN** it is built
- **THEN** the test output receives the room the follow-ups would have had

#### Scenario: No output

- **GIVEN** a description with no test output that is over the limit
- **WHEN** it is built
- **THEN** the follow-ups receive the room the output would have had

#### Scenario: A description that fits

- **WHEN** the description is within the limit
- **THEN** it is identical to the one built without a limit

### Requirement: A unit's test output keeps the failed tests and why they failed

The test output saved for a unit SHALL be made of one section per command, a failed command weighing more than a passing one,
and within a failed command SHALL keep, for each failed test, its identifier and its error lines before the remainder. A
profile that cannot read the failed tests SHALL keep the tail as before.

#### Scenario: Seven failed tests in a long log

- **GIVEN** a log longer than the budget with seven failed tests
- **WHEN** the output is saved
- **THEN** the identifier and error lines of all seven are present

#### Scenario: A profile without the reading

- **GIVEN** a profile that cannot read failed tests
- **WHEN** the output is saved
- **THEN** the tail is kept as before

### Requirement: The other assemblies and cuts use the same module

The earlier review rounds shown to a reviewer SHALL be sections of the same fitter, with open findings required, and the other
cuts of text to a size SHALL use the shared cuts and keep what they keep.

#### Scenario: Earlier rounds over the size

- **GIVEN** earlier rounds that exceed their size
- **WHEN** they are assembled
- **THEN** open findings are kept in full and the rest is reduced, with a note of how many were left out
