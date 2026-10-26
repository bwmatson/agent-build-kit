# review-classification Specification

## Purpose
TBD - created by archiving change review-policy-and-verdict-recorded-in-shadow. Update Purpose after archive.

## Requirements

### Requirement: The reviewer classifies the review tier a unit deserves

When review is enabled, the reviewer's reply SHALL carry a `classification`, `auto`, `light` or `full`, judged against the criteria in
its prompt: whether the change crosses a boundary another system depends on, whether it is hard to undo, and what behaviour the tests
do not exercise. When the classification is above the unit's planned estimate, the reply SHALL carry `drivers`, the groups or files
that account for it. A classification that is missing, not one of the three, or unparseable SHALL be recorded as `full`. Parsing the
reply SHALL still never raise, and the reply's other fields SHALL mean what they meant.

#### Scenario: Classification above the estimate

- **GIVEN** a unit planned `auto`
- **WHEN** the reviewer returns `light` with drivers naming one file
- **THEN** both are recorded for the unit

#### Scenario: A missing classification

- **WHEN** the reviewer's reply has no classification
- **THEN** the unit's recorded classification is `full`, and the reply's approval and findings are read as before

#### Scenario: An unknown value

- **WHEN** the reply gives a classification that is not one of the three
- **THEN** it is recorded as `full`

### Requirement: The classification criteria are part of the review prompt

The criteria the reviewer classifies by SHALL be text in the review prompt that the framework ships, and no setting SHALL change them.
The prompt SHALL tell the reviewer that its classification can raise the review a unit gets and never lower it.

#### Scenario: The prompt

- **WHEN** the review prompt is built with review enabled
- **THEN** it names the three tiers, the criteria, and that the classification can only raise review

### Requirement: The reviewer's escalation to a person is unchanged and independent of the classification

The reviewer's `needs_human` and `escalate` outputs SHALL keep their meaning and their effect: a reply that sets either SHALL hold the
unit for a person with the cause it sets today, before the unit is approved or pushed. A classification in the same reply SHALL
neither clear nor set an escalation, and an escalation SHALL neither raise nor lower the classification recorded for the round. The
prompt SHALL describe the two as answers to different questions.

#### Scenario: Both in one reply

- **WHEN** a reply sets `needs_human` and classifies the unit `auto`
- **THEN** the unit is held for a person as before, and the recorded classification is `auto`

#### Scenario: A classification alone

- **WHEN** a reply sets neither field and classifies the unit `full`
- **THEN** the unit is not held for a person, and the classification is recorded
