## ADDED Requirements

### Requirement: Review does not spend a round on what tier 1 checks about the changelog

A reviewer SHALL be told that the changelog's form and wording are not findings while
tier 1's changelog check passes. A changelog entry that claims something the code does
not do SHALL still be a finding.

#### Scenario: A passing check, awkward wording

- **GIVEN** an entry that passes the changelog check but is phrased awkwardly
- **WHEN** the unit is reviewed
- **THEN** the wording is not raised

#### Scenario: A false claim

- **GIVEN** an entry that describes behaviour the change does not implement
- **WHEN** the unit is reviewed
- **THEN** it is raised as a finding
