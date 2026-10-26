# pr-description Specification

## Purpose
TBD - created by archiving change pr-description-says-why. Update Purpose after archive.

## Requirements

### Requirement: The description opens with why the change exists

A pull request's description SHALL begin with a Why section taken from the `Why` section of the proposal of the
change the unit belongs to, cut at a paragraph boundary to a configured budget with a pointer to the full proposal
when cut. A unit that builds part of a change SHALL say the reason is the change's, and a unit that carries several
changes SHALL show one block for each. When the proposal cannot be read or has no such section the description
SHALL omit the section.

#### Scenario: A proposal with a short Why

- **GIVEN** a unit of a change whose proposal Why is two short paragraphs
- **WHEN** the pull request is opened
- **THEN** the description starts with that text in full

#### Scenario: A long Why

- **GIVEN** a Why longer than the budget
- **WHEN** the description is built
- **THEN** it is cut at a paragraph boundary, ends with an ellipsis, and points to the full proposal

#### Scenario: A part of a change

- **GIVEN** a unit that builds only the second group of a change
- **WHEN** the description is built
- **THEN** the section says the reason is the change's

#### Scenario: No proposal

- **WHEN** the proposal cannot be read
- **THEN** the section is omitted and the rest of the description is unchanged

### Requirement: The description says what the pull request does

After the Why, the description SHALL state the goal of the unit, taken from the "Done when" sentence under each of
its task group headings, and SHALL list the core changes written by the reviewer. A group without a "Done when"
sentence SHALL contribute no goal.

#### Scenario: Goal and changes

- **GIVEN** a unit whose group says "Done when a loopback server answers the read endpoints" and an approved
  verdict with three core changes
- **WHEN** the description is built
- **THEN** it shows that goal and the three changes under a heading for what the pull request does

#### Scenario: A group with no goal

- **GIVEN** a group with no "Done when" sentence
- **WHEN** the description is built
- **THEN** no goal is shown for it and nothing else changes

### Requirement: The reviewer describes the branch when it approves

An approving verdict MAY carry a description with a summary and a list of core changes. When it does, the
description SHALL be stored with the approval, SHALL replace any earlier one on a later approval, and SHALL be shown
in the pull request description. A missing or malformed description SHALL be ignored without costing a review round
and the goal alone SHALL be shown. A push made with the rounds spent SHALL use the last stored description if any.

#### Scenario: An approval with a description

- **WHEN** the reviewer approves with a description
- **THEN** it is stored with the approval and appears in the next pull request description

#### Scenario: A later approval

- **GIVEN** a stored description and a rework that is approved with a new one
- **WHEN** the pull request description is rebuilt
- **THEN** it shows the new description only

#### Scenario: A malformed description

- **WHEN** an approving verdict carries a description that does not parse
- **THEN** the approval stands, no round is spent, and the goal alone is shown

#### Scenario: Rounds spent

- **GIVEN** a unit pushed with its rounds spent and an earlier stored description
- **WHEN** the description is built
- **THEN** it shows the stored description

### Requirement: Process text follows the new sections

The stack position, scope, assumptions, verification and left-for-later sections SHALL follow the Why and what
sections, and the paragraph on how the unit was built SHALL be a single line.

#### Scenario: Order

- **WHEN** a description is built
- **THEN** the Why and what sections come before the stack position and scope

### Requirement: A recorded follow-up appears once

The description SHALL list each distinct follow-up one time, in its located form when it has one.

#### Scenario: The same finding in two forms

- **GIVEN** a finding recorded as a summary and again as a `file:line` line
- **WHEN** the description is built
- **THEN** it appears once, as the located line

### Requirement: The new sections have the highest weight when the description is fitted

The Why, the goal and the core changes SHALL be sections of the description's fit with the highest weight, with a
smallest form that is reserved before the budget is shared, and the Why SHALL have a ceiling of the configured length. The
follow-ups, the test output and the process lines SHALL have lower weights. The limit SHALL be the lowest any host allows,
and the sharing of the budget, including the passing on of what a section does not use, SHALL be that of the shared fitter.

#### Scenario: A description over the limit

- **GIVEN** a description over the limit
- **WHEN** it is fitted
- **THEN** the test output, follow-ups and process lines are reduced first, and the goal and core changes are still present

#### Scenario: A very small limit

- **GIVEN** a limit smaller than the Why, goal and changes together
- **WHEN** it is fitted
- **THEN** the smallest forms of the goal and changes are reserved first and the Why is cut to its smallest form

#### Scenario: A short Why

- **GIVEN** a Why shorter than its share
- **WHEN** it is fitted
- **THEN** the room it does not use goes to the other sections
